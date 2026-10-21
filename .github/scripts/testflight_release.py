"""Reviewable manual-signing draft. Never run without the user's release approval.

All subprocess output and signing material stay in RUNNER_TEMP. Only the explicit
allow-list in safe_evidence() may become a public artifact. Apple calls are GETs
except the explicitly requested xcodebuild export/upload. No provisioning APIs.
"""
import base64
import datetime as dt
import json
import os
import pathlib
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BUNDLE_ID = "jp.kb-dev.railvelo"
APP_ID = "6824978233"
VERSION = "0.5.0"
SECRET_NAMES = (
    "RAILVELO_TEAM_ID", "DISTRIBUTION_P12_BASE64", "DISTRIBUTION_P12_PASSWORD",
    "PROVISIONING_PROFILE_BASE64", "ASC_API_KEY_P8_BASE64", "ASC_KEY_ID", "ASC_ISSUER_ID",
)


class ReleaseError(Exception):
    """Messages are fixed codes, never raw subprocess/HTTP/credential text."""


class PrivateCommandError(ReleaseError):
    """Only a fixed category and numeric exit status may leave the private log."""
    def __init__(self, category, returncode=None):
        categories = {"missing_profile", "signing_identity", "authentication", "sdk", "compile",
                      "upload", "network", "timeout", "execution", "unknown"}
        if category not in categories:
            category = "unknown"
        self.category = category
        self.returncode = returncode if type(returncode) is int else None
        code = str(self.returncode) if self.returncode is not None else "unknown"
        super().__init__("private_command_failed:category=" + category + ":returncode=" + code)


def private_failure_category(output):
    """Match known diagnostic phrases; never copy any log text into the result."""
    text = output.lower()
    phrases = (
        ("missing_profile", (b"no profiles for", b"requires a provisioning profile", b"provisioning profile not found",
                             b"no provisioning profile", b"doesn't include the selected signing certificate")),
        ("signing_identity", (b"no signing certificate", b"no applicable signing identities", b"errsecinternalcomponent",
                              b"code signing is required", b"codesign failed", b"no identity found",
                              b"code object is not signed at all")),
        ("authentication", (b"failed to authenticate", b"authentication credentials", b"authentication failed",
                            b"unable to authenticate", b"not authorized", b"unauthorized", b"invalid jwt", b"invalid credentials")),
        ("network", (b"could not resolve host", b"network connection was lost", b"not connected to the internet",
                     b"connection timed out", b"could not connect to the server", b"ssl connection error")),
        ("sdk", (b"sdk cannot be located", b"unable to find a destination matching", b"sdk is not supported",
                 b"unable to find an sdk", b"unable to find a specification for sdk")),
        ("upload", (b"upload failed", b"error uploading", b"asset validation failed", b"validation failed",
                    b"app store connect operation failed", b"transporter", b"itms-")),
        ("compile", (b"swift compiler error", b"compile failed", b"swiftcompile", b"compilec ",
                     b"** build failed **", b"** archive failed **")),
    )
    for category, needles in phrases:
        sdk_missing = category == "sdk" and re.search(rb"\bsdk\b[^\r\n]{0,160}\bcannot be located\b", text)
        if sdk_missing or any(needle in text for needle in needles):
            return category
    return "unknown"


def require(condition, code):
    if not condition:
        raise ReleaseError(code)


def mask(value):
    encoded = str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::add-mask::" + encoded, flush=True)


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
    os.chmod(path, 0o600)


def decode_secret(value):
    try:
        result = base64.b64decode("".join(value.split()), validate=True)
    except (ValueError, TypeError) as error:
        raise ReleaseError("invalid_base64_secret") from error
    require(0 < len(result) <= 20_000_000, "secret_size_invalid")
    return result


def build_number(run_number, attempt):
    require(bool(re.fullmatch(r"[1-9][0-9]{0,8}", run_number or "")), "invalid_run_number")
    require(bool(re.fullmatch(r"[1-9][0-9]{0,8}", attempt or "")), "invalid_run_attempt")
    return "500." + run_number + "." + attempt


def utc(value):
    require(isinstance(value, dt.datetime), "invalid_expiration")
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def validate_profile(profile, team, certificate_der, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    require(isinstance(profile, dict), "invalid_profile")
    require(profile.get("TeamIdentifier") == [team], "profile_team_mismatch")
    platforms = profile.get("Platform")
    # Apple iOS App Store profiles may also list its compatible vision platforms.
    require(isinstance(platforms, list) and all(isinstance(value, str) for value in platforms)
            and "iOS" in platforms and set(platforms) <= {"iOS", "xrOS", "visionOS"}, "profile_platform_mismatch")
    require("ProvisionedDevices" not in profile, "device_profile_rejected")
    require(profile.get("ProvisionsAllDevices", False) is False, "enterprise_profile_rejected")
    require(utc(profile.get("ExpirationDate")) > now, "profile_expired")
    entitlements = profile.get("Entitlements", {})
    require(entitlements.get("application-identifier") == team + "." + BUNDLE_ID, "profile_app_mismatch")
    require(entitlements.get("com.apple.developer.team-identifier") == team, "profile_entitlement_team_mismatch")
    require(entitlements.get("get-task-allow") is False, "debug_profile_rejected")
    require(entitlements.get("beta-reports-active") is True, "app_store_profile_required")
    certificates = profile.get("DeveloperCertificates", [])
    require(isinstance(certificates, list) and certificate_der in certificates, "profile_certificate_mismatch")
    try:
        profile_uuid = str(uuid.UUID(profile.get("UUID", ""))).upper()
    except (ValueError, TypeError, AttributeError) as error:
        raise ReleaseError("invalid_profile_uuid") from error
    return profile_uuid


def require_export_support(help_text):
    for key, kind in (("method", "String"), ("destination", "String"), ("signingStyle", "String"),
                      ("signingCertificate", "String"), ("provisioningProfiles", "Dictionary"),
                      ("teamID", "String"), ("manageAppVersionAndBuildNumber", "Bool"),
                      ("testFlightInternalTestingOnly", "Bool")):
        require(re.search(r"\b" + key + r"\s*:\s*" + kind + r"\b", help_text) is not None,
                "unsupported_export_option_" + key)
    method = re.search(r"\bmethod\s*:\s*String\b(.*?)(?=\n\s*[A-Za-z]\w*\s*:\s*(?:String|Bool|Dictionary|Array)\b|\Z)", help_text, re.S)
    require(method is not None and "app-store-connect" in method.group(1), "unsupported_app_store_connect_method")


def validate_signed_entitlements(entitlements, team):
    require(entitlements.get("application-identifier") == team + "." + BUNDLE_ID, "signed_app_id_mismatch")
    require(entitlements.get("com.apple.developer.team-identifier") == team, "signed_team_mismatch")
    require(entitlements.get("get-task-allow") is False, "signed_debug_entitlement")


def evaluate_build(document, number):
    """Return safe state or None while Apple has not exposed the exact build."""
    builds = document.get("data")
    require(isinstance(builds, list), "asc_response_invalid")
    require(len(builds) <= 1, "asc_ambiguous_build")
    if not builds:
        return None
    build = builds[0]
    attributes = build.get("attributes", {})
    require(attributes.get("version") == number, "asc_build_mismatch")
    relationships = build.get("relationships", {})
    require(relationships.get("app", {}).get("data", {}).get("id") == APP_ID, "asc_app_mismatch")
    applications = [resource for resource in document.get("included", [])
                    if resource.get("type") == "apps" and resource.get("id") == APP_ID]
    require(len(applications) == 1 and applications[0].get("attributes", {}).get("bundleId") == BUNDLE_ID,
            "asc_included_app_mismatch")
    prerelease_id = relationships.get("preReleaseVersion", {}).get("data", {}).get("id")
    prereleases = [r for r in document.get("included", [])
                   if r.get("type") == "preReleaseVersions" and r.get("id") == prerelease_id]
    require(len(prereleases) == 1 and prereleases[0].get("attributes", {}).get("version") == VERSION,
            "asc_version_mismatch")
    state = attributes.get("processingState")
    require(state in ("PROCESSING", "VALID", "INVALID", "FAILED"), "asc_processing_state_unknown")
    require(state not in ("INVALID", "FAILED"), "asc_processing_failed")
    if state == "VALID":
        require(attributes.get("expired") is False, "asc_build_expired")
        require(attributes.get("buildAudienceType") == "INTERNAL_ONLY", "asc_internal_only_not_confirmed")
    return state


def safe_evidence(sha, number, phase, success, uploaded, valid, cleanup_ok):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "invalid_evidence_sha")
    require(bool(re.fullmatch(r"500\.[1-9][0-9]{0,8}\.[1-9][0-9]{0,8}", number)), "invalid_evidence_build")
    require(phase in {"preflight", "materials", "keychain", "archive", "verify", "upload", "processing", "complete"},
            "invalid_evidence_phase")
    return {"schema_version": 1, "repository": "KANABUNN/RailVelo", "source_sha": sha,
            "bundle_id": BUNDLE_ID, "app_id": APP_ID, "version": VERSION, "build": number,
            "phase": phase, "success": bool(success), "upload_completed": bool(uploaded),
            "processing_valid_internal_only": bool(valid), "cleanup_ok": bool(cleanup_ok),
            "testers_modified": False, "profiles_generated": False, "certificates_generated": False,
            "device_acceptance": "not_verified"}


def runtime_paths():
    temp = pathlib.Path(os.environ["RUNNER_TEMP"]).resolve()
    return temp, temp / "railvelo-testflight-private", temp / "railvelo-testflight-state.json"


class PrivateRunner:
    def __init__(self, folder):
        self.folder = folder
        self.log = folder / "commands.log"
        self.environment = {key: value for key, value in os.environ.items() if key not in SECRET_NAMES and key != "GH_TOKEN"}

    def call(self, arguments, timeout=300, accepted=(0,)):
        with open(self.log, "ab") as log:
            os.chmod(self.log, 0o600)
            try:
                result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=self.environment, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as error:
                raise PrivateCommandError("timeout") from error
            except OSError as error:
                raise PrivateCommandError("execution") from error
            log.write(result.stdout)
        if result.returncode not in accepted:
            raise PrivateCommandError(private_failure_category(result.stdout), result.returncode)
        return result.stdout


def save_state(path, state):
    # An interrupted update must leave the previous usable restoration snapshot.
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(json.dumps(state).encode())
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup():
    temp, folder, state_path = runtime_paths()
    if not state_path.exists():
        if folder.exists():
            shutil.rmtree(folder)
        return True
    state = json.loads(state_path.read_text())
    keychain = folder / "signing.keychain-db"
    require(state.get("folder") == str(folder), "cleanup_state_invalid")
    successful = True
    # Never echo the original keychain paths, profile UUIDs, or subprocess output.
    for command in (["/usr/bin/security", "list-keychains", "-d", "user", "-s", *state["search_list"]],
                    ["/usr/bin/security", "default-keychain", "-d", "user", "-s", state["default_keychain"]]):
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            successful = False
    try:
        deletion = subprocess.run(["/usr/bin/security", "delete-keychain", str(keychain)], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, check=False, timeout=30)
        if deletion.returncode != 0 and keychain.exists():
            successful = False
    except (OSError, subprocess.SubprocessError):
        successful = False
    for profile in state.get("profiles", []):
        path, backup = pathlib.Path(profile["path"]), pathlib.Path(profile["backup"])
        permitted = (pathlib.Path.home() / "Library/MobileDevice/Provisioning Profiles",
                     pathlib.Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles")
        require(path.parent in permitted and re.fullmatch(r"[0-9A-F-]{36}\.mobileprovision", path.name), "cleanup_profile_path_invalid")
        require(backup.parent == folder, "cleanup_backup_path_invalid")
        try:
            if profile["existed"]:
                shutil.copy2(backup, path)
                os.chmod(path, profile["mode"])
            else:
                path.unlink(missing_ok=True)
        except OSError:
            successful = False
    if successful:
        shutil.rmtree(folder, ignore_errors=False)
        state_path.unlink(missing_ok=True)
    return successful


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReleaseError("asc_redirect_rejected")


def asc_get(path, p8_path, key_id, issuer):
    import jwt
    now = int(time.time())
    token = jwt.encode({"iss": issuer, "iat": now - 5, "exp": now + 600, "aud": "appstoreconnect-v1"},
                       p8_path.read_bytes(), algorithm="ES256", headers={"kid": key_id, "typ": "JWT"})
    require(path.startswith("/v1/") and not path.startswith("//"), "asc_path_rejected")
    request = urllib.request.Request("https://api.appstoreconnect.apple.com" + path,
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError, OSError) as error:
        raise ReleaseError("asc_read_failed") from error


def builds_path(number):
    return "/v1/builds?" + urllib.parse.urlencode({
        "filter[app]": APP_ID, "filter[version]": number, "filter[preReleaseVersion.version]": VERSION,
        "include": "preReleaseVersion,app", "fields[builds]": "version,processingState,buildAudienceType,expired,app,preReleaseVersion",
        "fields[preReleaseVersions]": "version", "fields[apps]": "bundleId", "limit": 2,
    })


def release():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    require(sys.platform == "darwin", "macos_required")
    os.umask(0o077)
    sha = os.environ.get("SOURCE_SHA", "")
    number = build_number(os.environ.get("GITHUB_RUN_NUMBER"), os.environ.get("GITHUB_RUN_ATTEMPT"))
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "full_source_sha_required")
    require(os.environ.get("GITHUB_REPOSITORY") == "KANABUNN/RailVelo"
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "release_context_rejected")
    temp, folder, state_path = runtime_paths()
    require(not folder.exists() and not state_path.exists(), "stale_private_state")
    folder.mkdir(mode=0o700)
    runner = PrivateRunner(folder)
    evidence_path = temp / "railvelo-testflight-safe" / "evidence.json"
    phase, uploaded, valid, success = "preflight", False, False, False
    state = None
    failure = None
    cleanup_ok = True
    try:
        require_export_support(runner.call(["/usr/bin/xcodebuild", "-help"]).decode(errors="replace"))
        source = pathlib.Path(os.environ["GITHUB_WORKSPACE"]).resolve() / "source"
        require((source / "ios/RailVelo.xcodeproj").is_dir(), "source_project_missing")
        for name in SECRET_NAMES:
            require(bool(os.environ.get(name)), "required_secret_missing")
        team, key_id, issuer = (os.environ[name] for name in ("RAILVELO_TEAM_ID", "ASC_KEY_ID", "ASC_ISSUER_ID"))
        require(bool(re.fullmatch(r"[A-Z0-9]{10}", team)), "invalid_team_identifier")
        require(bool(re.fullmatch(r"[A-Za-z0-9]{10}", key_id)), "invalid_api_key_identifier")
        try:
            uuid.UUID(issuer)
        except ValueError as error:
            raise ReleaseError("invalid_api_issuer") from error
        mask(team); mask(key_id); mask(issuer)
        phase = "materials"
        p12_data = decode_secret(os.environ["DISTRIBUTION_P12_BASE64"])
        key, certificate, _ = pkcs12.load_key_and_certificates(p12_data, os.environ["DISTRIBUTION_P12_PASSWORD"].encode())
        require(key is not None and certificate is not None, "p12_private_identity_missing")
        now = dt.datetime.now(dt.timezone.utc)
        require(certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc, "distribution_certificate_expired")
        cn = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        ou = certificate.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
        require(len(cn) == 1 and cn[0].value.startswith("Apple Distribution:"), "distribution_certificate_type_mismatch")
        require(len(ou) == 1 and ou[0].value == team, "distribution_certificate_team_mismatch")
        mask(cn[0].value)
        require(ExtendedKeyUsageOID.CODE_SIGNING in certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value,
                "distribution_certificate_usage_mismatch")
        public_format = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        require(key.public_key().public_bytes(*public_format) == certificate.public_key().public_bytes(*public_format), "p12_key_mismatch")
        certificate_der = certificate.public_bytes(serialization.Encoding.DER)
        identity = certificate.fingerprint(hashes.SHA1()).hex().upper()
        mask(identity)
        p12_path, profile_path = folder / "distribution.p12", folder / "profile.mobileprovision"
        private_write(p12_path, p12_data)
        private_write(profile_path, decode_secret(os.environ["PROVISIONING_PROFILE_BASE64"]))
        profile = plistlib.loads(runner.call(["/usr/bin/security", "cms", "-D", "-i", str(profile_path)]))
        profile_uuid = validate_profile(profile, team, certificate_der, now)
        mask(profile_uuid)
        p8_path = folder / "AuthKey.p8"
        private_write(p8_path, decode_secret(os.environ["ASC_API_KEY_P8_BASE64"]))
        api_key = serialization.load_pem_private_key(p8_path.read_bytes(), password=None)
        require(isinstance(api_key, ec.EllipticCurvePrivateKey) and isinstance(api_key.curve, ec.SECP256R1), "api_key_not_es256")
        app = asc_get("/v1/apps/" + APP_ID + "?fields%5Bapps%5D=bundleId", p8_path, key_id, issuer)
        require(app.get("data", {}).get("attributes", {}).get("bundleId") == BUNDLE_ID, "asc_access_or_bundle_mismatch")
        require(asc_get(builds_path(number), p8_path, key_id, issuer).get("data") == [], "build_number_already_exists")
        search_list = shlex.split(runner.call(["/usr/bin/security", "list-keychains", "-d", "user"]).decode())
        default = shlex.split(runner.call(["/usr/bin/security", "default-keychain", "-d", "user"]).decode())
        require(search_list and len(default) == 1, "keychain_snapshot_failed")
        state = {"folder": str(folder), "search_list": search_list, "default_keychain": default[0], "profiles": []}
        save_state(state_path, state)
        phase = "keychain"
        keychain, password = folder / "signing.keychain-db", secrets.token_urlsafe(32)
        runner.call(["/usr/bin/security", "create-keychain", "-p", password, str(keychain)])
        runner.call(["/usr/bin/security", "set-keychain-settings", "-lut", "3600", str(keychain)])
        runner.call(["/usr/bin/security", "unlock-keychain", "-p", password, str(keychain)])
        runner.call(["/usr/bin/security", "import", str(p12_path), "-P", os.environ["DISTRIBUTION_P12_PASSWORD"],
                     "-T", "/usr/bin/codesign", "-T", "/usr/bin/security", "-f", "pkcs12", "-k", str(keychain)])
        runner.call(["/usr/bin/security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", password, str(keychain)])
        runner.call(["/usr/bin/security", "list-keychains", "-d", "user", "-s", str(keychain), *search_list])
        for index, directory in enumerate((pathlib.Path.home() / "Library/MobileDevice/Provisioning Profiles",
                                           pathlib.Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles")):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = directory / (profile_uuid + ".mobileprovision")
            require(not target.is_symlink() and (not target.exists() or target.is_file()), "existing_profile_path_rejected")
            backup = folder / ("profile-backup-" + str(index))
            if target.exists():
                shutil.copy2(target, backup); os.chmod(backup, 0o600)
            state["profiles"].append({"path": str(target), "backup": str(backup), "existed": target.exists(),
                                      "mode": target.stat().st_mode & 0o777 if target.exists() else 0o600})
            save_state(state_path, state)
            private_write(target, profile_path.read_bytes())
        phase = "archive"
        archive = folder / "RailVelo.xcarchive"
        runner.call(["/usr/bin/xcodebuild", "-project", str(source / "ios/RailVelo.xcodeproj"), "-scheme", "RailVelo",
                     "-configuration", "Release", "-destination", "generic/platform=iOS", "-archivePath", str(archive),
                     "-derivedDataPath", str(folder / "DerivedData"), "CODE_SIGN_STYLE=Manual", "DEVELOPMENT_TEAM=" + team,
                     "CODE_SIGN_IDENTITY=" + identity, "PROVISIONING_PROFILE_SPECIFIER=" + profile_uuid,
                     "MARKETING_VERSION=" + VERSION, "CURRENT_PROJECT_VERSION=" + number, "archive"], timeout=1200)
        phase = "verify"
        application = archive / "Products/Applications/RailVelo.app"
        info = plistlib.loads((application / "Info.plist").read_bytes())
        require((info.get("CFBundleIdentifier"), info.get("CFBundleShortVersionString"), info.get("CFBundleVersion"))
                == (BUNDLE_ID, VERSION, number), "archive_identity_mismatch")
        require((application / "embedded.mobileprovision").read_bytes() == profile_path.read_bytes(), "archive_profile_mismatch")
        runner.call(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(application)])
        output = runner.call(["/usr/bin/codesign", "-d", "--entitlements", ":-", str(application)])
        start, end = output.find(b"<?xml"), output.find(b"</plist>")
        require(start >= 0 and end >= start, "signed_entitlements_unreadable")
        validate_signed_entitlements(plistlib.loads(output[start:end + len(b"</plist>")]), team)
        certificate_prefix = folder / "signed-certificate-"
        runner.call(["/usr/bin/codesign", "-d", "--extract-certificates", str(certificate_prefix), str(application)])
        require(pathlib.Path(str(certificate_prefix) + "0").read_bytes() == certificate_der, "archive_certificate_mismatch")
        options = {"method": "app-store-connect", "destination": "upload", "signingStyle": "manual", "teamID": team,
                   "signingCertificate": identity, "provisioningProfiles": {BUNDLE_ID: profile_uuid},
                   "manageAppVersionAndBuildNumber": False, "testFlightInternalTestingOnly": True}
        export_options = folder / "ExportOptions.plist"
        private_write(export_options, plistlib.dumps(options))
        phase = "upload"
        runner.call(["/usr/bin/xcodebuild", "-exportArchive", "-archivePath", str(archive), "-exportPath", str(folder / "Export"),
                     "-exportOptionsPlist", str(export_options), "-authenticationKeyPath", str(p8_path),
                     "-authenticationKeyID", key_id, "-authenticationKeyIssuerID", issuer], timeout=1200)
        uploaded = True
        phase = "processing"
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            if evaluate_build(asc_get(builds_path(number), p8_path, key_id, issuer), number) == "VALID":
                valid = True
                break
            time.sleep(30)
        require(valid, "asc_processing_timeout")
        phase, success = "complete", True
    except BaseException as error:
        failure = str(error) if isinstance(error, ReleaseError) else "unexpected_private_failure"
    finally:
        try:
            cleanup_ok = cleanup() if state_path.exists() else True
            if not state_path.exists() and folder.exists():
                shutil.rmtree(folder)
        except BaseException:
            cleanup_ok = False
        private_write(evidence_path, (json.dumps(safe_evidence(sha, number, phase, success and cleanup_ok, uploaded, valid, cleanup_ok), indent=2) + "\n").encode())
    if failure or not cleanup_ok:
        print("TestFlight draft stopped: " + (failure or "cleanup_failed"), file=sys.stderr)
        return 1
    print("Upload processed as VALID and INTERNAL_ONLY. Tester assignment remains manual.")
    return 0


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments == ["cleanup"]:
        try:
            return 0 if cleanup() else 1
        except BaseException:
            print("Private signing cleanup requires attention.", file=sys.stderr)
            return 1
    if arguments:
        print("TestFlight draft stopped: unsupported_arguments", file=sys.stderr)
        return 1
    try:
        return release()
    except BaseException:
        print("TestFlight draft stopped before signing: preflight_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

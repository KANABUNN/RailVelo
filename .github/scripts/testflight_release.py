"""Reviewable manual-signing draft. Never run without the user's release approval.

All subprocess output and signing material stay in RUNNER_TEMP. Only the explicit
allow-list in safe_evidence() may become a public artifact. Apple calls are GETs
except the explicitly requested xcodebuild export/upload. No provisioning APIs.
"""
import base64
import datetime as dt
import gzip
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
ARCHIVE_DIAGNOSTIC_SCHEMA = "railvelo.failed-archive.v1"
MAX_ARCHIVE_DIAGNOSTIC_RAW_BYTES = 20_000_000
MAX_ARCHIVE_DIAGNOSTIC_FILE_BYTES = 30_000_000
SECRET_NAMES = (
    "RAILVELO_TEAM_ID", "DISTRIBUTION_P12_BASE64", "DISTRIBUTION_P12_PASSWORD",
    "PROVISIONING_PROFILE_BASE64", "ASC_API_KEY_P8_BASE64", "ASC_KEY_ID", "ASC_ISSUER_ID",
)


class ReleaseError(Exception):
    """Messages are fixed codes, never raw subprocess/HTTP/credential text."""


CATEGORY_PRIORITY = (
    "profile_target_mismatch", "certificate_chain", "signing_configuration", "private_key",
    "missing_profile", "signing_identity", "authentication", "network", "sdk", "package",
    "asset_catalog", "resource", "link", "compile", "signing", "build_phase", "archive", "upload",
    "timeout", "execution", "unknown",
)
TAG_CATEGORIES = {
    "profile_target_mismatch": "profile_target_mismatch",
    "provisioning_settings_conflict": "signing_configuration",
    "development_signing_conflict": "signing_configuration",
    "development_team_required": "signing_configuration",
    "profile_certificate_mismatch": "signing_configuration",
    "profile_entitlements_mismatch": "signing_configuration",
    "entitlements_packaging_failed": "signing_configuration",
    "bundle_registration_failed": "signing_configuration",
    "certificate_chain_untrusted": "certificate_chain",
    "private_key_missing": "private_key",
    "keychain_access_denied": "private_key",
    "profile_missing": "missing_profile",
    "signing_identity_missing": "signing_identity",
    "certificate_expired_or_revoked": "signing_identity",
    "codesign_internal_error": "signing",
    "codesign_failed": "signing",
    "authentication_failed": "authentication",
    "network_failed": "network",
    "sdk_unavailable": "sdk",
    "package_resolution_failed": "package",
    "package_product_missing": "package",
    "package_download_failed": "package",
    "asset_catalog_app_icon_missing": "asset_catalog",
    "asset_catalog_failed": "asset_catalog",
    "input_file_missing": "resource",
    "input_file_list_unreadable": "resource",
    "plist_invalid": "resource",
    "resource_processing_failed": "resource",
    "linker_undefined_symbols": "link",
    "linker_duplicate_symbols": "link",
    "linker_library_missing": "link",
    "linker_platform_mismatch": "link",
    "linker_failed": "link",
    "compiler_error": "compile",
    "build_phase_failed": "build_phase",
    "archive_invalid": "archive",
    "archive_processing_failed": "archive",
    "upload_failed": "upload",
    "unrecognized_failed_command": "unknown",
}
# Names come only from this table, never from an arbitrary captured command.
FAILED_COMMAND_TAGS = {
    "CodeSign": "codesign_failed", "SwiftCompile": "compiler_error",
    "ProcessProductPackaging": "entitlements_packaging_failed",
    "ProcessProductPackagingDER": "entitlements_packaging_failed",
    "SwiftEmitModule": "compiler_error", "SwiftDriver": "compiler_error",
    "CompileSwiftSources": "compiler_error", "CompileC": "compiler_error",
    "PrecompileSwiftBridgingHeader": "compiler_error", "Ld": "linker_failed",
    "CreateUniversalBinary": "linker_failed", "Strip": "linker_failed",
    "CompileAssetCatalog": "asset_catalog_failed", "CompileAssetCatalogVariant": "asset_catalog_failed",
    "LinkAssetCatalog": "asset_catalog_failed", "GenerateAssetSymbols": "asset_catalog_failed",
    "CpResource": "resource_processing_failed", "Copy": "resource_processing_failed",
    "CopySwiftLibs": "resource_processing_failed", "CopyPlistFile": "resource_processing_failed",
    "ProcessInfoPlistFile": "resource_processing_failed", "MkDir": "resource_processing_failed",
    "PhaseScriptExecution": "build_phase_failed", "ResolvePackageDependencies": "package_resolution_failed",
    "Validate": "archive_processing_failed", "GenerateDSYMFile": "archive_processing_failed",
    "RegisterExecutionPolicyException": "archive_processing_failed",
    "ProcessXCFramework": "resource_processing_failed", "ValidateEmbeddedBinary": "archive_processing_failed",
}


class PrivateCommandError(ReleaseError):
    """Only a fixed category and numeric exit status may leave the private log."""
    def __init__(self, category, returncode=None, diagnostics=None):
        if category not in CATEGORY_PRIORITY:
            category = "unknown"
        self.category = category
        self.returncode = returncode if type(returncode) is int else None
        detail = diagnostics or {"category": category, "tags": [], "failed_commands": [], "unknown_error_lines": 0}
        self.diagnostics = validate_command_diagnostics({**detail, "returncode": self.returncode})
        require(self.diagnostics["category"] == category, "invalid_command_diagnostics")
        code = str(self.returncode) if self.returncode is not None else "unknown"
        super().__init__("private_command_failed:category=" + category + ":returncode=" + code)


def private_command_diagnostics(output):
    """Reduce private output to fixed tags/command names and a numeric count."""
    text = output.decode("utf-8", "replace").lower()
    phrases = (
        ("profile_target_mismatch", ("does not support provisioning profiles",)),
        ("provisioning_settings_conflict", ("conflicting provisioning settings",)),
        ("development_signing_conflict", ("automatically signed for development, but",)),
        ("development_team_required", ("requires a development team", "select a development team in the signing")),
        ("profile_certificate_mismatch", ("doesn't include the selected signing certificate",)),
        ("entitlements_packaging_failed", ("code signing entitlements file was modified",)),
        ("bundle_registration_failed", ("failed to register bundle identifier",)),
        ("certificate_chain_untrusted", ("unable to build chain to self-signed root", "cssmerr_tp_not_trusted",
                                         "cssmerr_tp_invalid_cert_anchor", "errsecnottrusted")),
        ("private_key_missing", ("private key is not installed", "private key is missing", "missing private key",
                                 "no private key", "does not have a private key")),
        ("keychain_access_denied", ("user interaction is not allowed", "errsecinteractionnotallowed",
                                    "cssmerr_csp_no_user_interaction", "errsecauthfailed")),
        ("profile_missing", ("no profiles for", "requires a provisioning profile", "provisioning profile not found",
                              "no provisioning profile")),
        ("signing_identity_missing", ("no signing certificate", "no applicable signing identities", "no identity found")),
        ("certificate_expired_or_revoked", ("certificate has either expired or has been revoked",)),
        ("codesign_internal_error", ("errsecinternalcomponent",)),
        ("codesign_failed", ("code signing is required", "codesign failed", "code object is not signed at all")),
        ("authentication_failed", ("failed to authenticate", "authentication credentials", "authentication failed",
                                    "unable to authenticate", "not authorized", "unauthorized", "invalid jwt", "invalid credentials")),
        ("network_failed", ("could not resolve host", "network connection was lost", "not connected to the internet",
                             "connection timed out", "could not connect to the server", "ssl connection error")),
        ("sdk_unavailable", ("sdk cannot be located", "unable to find a destination matching", "sdk is not supported",
                              "unable to find an sdk", "unable to find a specification for sdk")),
        ("package_resolution_failed", ("could not resolve package dependencies", "failed to resolve package dependencies")),
        ("package_product_missing", ("missing package product", "package product not found")),
        ("package_download_failed", ("failed downloading binary", "failed to download binary")),
        ("asset_catalog_app_icon_missing", ("none of the input catalogs contained a matching app icon set",)),
        ("input_file_missing", ("build input file cannot be found", "input file cannot be found", "no such file or directory")),
        ("input_file_list_unreadable", ("unable to load contents of file list", "unable to read file list")),
        ("plist_invalid", ("could not parse input file as a property list", "unable to read property list", "malformed property list")),
        ("linker_undefined_symbols", ("undefined symbols for architecture", "undefined symbol:")),
        ("linker_duplicate_symbols", ("duplicate symbol",)),
        ("linker_library_missing", ("library not found for", "framework not found")),
        ("linker_failed", ("linker command failed",)),
        ("compiler_error", ("swift compiler error", "compile failed", "compilation failed",
                             "error: emit-module command failed", "error: compile command failed",
                             "error: swiftc command failed", "error: no such module", "error: missing required module")),
        ("archive_invalid", ("not a valid archive", "archive is malformed", "archive not found")),
        ("upload_failed", ("upload failed", "error uploading", "asset validation failed", "validation failed",
                            "app store connect operation failed", "itms-")),
    )
    found, commands, unknown, summary_remaining = set(), set(), 0, 0
    for line in text.splitlines():
        if "the following build commands failed:" in line:
            summary_remaining = 30
            continue
        line_tags = {tag for tag, needles in phrases if any(needle in line for needle in needles)}
        error_line = re.search(r"\b(?:fatal\s+)?error\s*:|\berror domain\s*=|^\s*error\b", line) is not None
        if re.search(r"\bsdk\b[^\r\n]{0,160}\bcannot be located\b", line):
            line_tags.add("sdk_unavailable")
        if re.search(r"\.(?:swift|c|cc|cpp|m|mm|h|hpp):[0-9]+(?::[0-9]+)?:\s*(?:fatal\s+)?error:", line):
            line_tags.add("compiler_error")
        if error_line and (".xcassets:" in line or "actool" in line):
            line_tags.add("asset_catalog_failed")
        if error_line and ("building for" in line and "linking" in line or "file was built for" in line):
            line_tags.add("linker_platform_mismatch")
        if "provisioning profile" in line and any(phrase in line for phrase in (
                "does not match the bundle identifier", "doesn't match the entitlements", "doesn't support the")):
            line_tags.add("profile_entitlements_mismatch")
        command_failure = re.search(r"\bcommand\s+.+?\s+failed with (?:a\s+)?non[- ]?zero exit code\b", line) is not None
        first_token = line.split(maxsplit=1)[0] if line.strip() else ""
        known_command = False
        for command, tag in FAILED_COMMAND_TAGS.items():
            escaped = re.escape(command.lower())
            explicit = re.search(r"\bcommand\s+" + escaped + r"\s+failed with (?:a\s+)?non[- ]?zero exit code\b", line)
            summary = summary_remaining > 0 and first_token == command.lower()
            if explicit or summary:
                known_command = True
                commands.add(command)
                line_tags.add(tag)
        unknown_summary_command = (summary_remaining > 0 and bool(first_token) and not known_command
                                   and not first_token.startswith(("(", "**", "note:", "warning:")))
        if (command_failure and not known_command) or unknown_summary_command:
            line_tags.add("unrecognized_failed_command")
        if summary_remaining:
            summary_remaining -= 1
            if not line.strip() or re.match(r"\s*\([0-9]+ failures?\)", line):
                summary_remaining = 0
        if (error_line or command_failure or unknown_summary_command) and not line_tags - {"unrecognized_failed_command"}:
            unknown = min(unknown + 1, 1_000_000)
        found.update(line_tags)
    categories = {TAG_CATEGORIES[tag] for tag in found}
    category = next((value for value in CATEGORY_PRIORITY if value in categories), "unknown")
    return {"category": category, "tags": [tag for tag in TAG_CATEGORIES if tag in found],
            "failed_commands": [name for name in FAILED_COMMAND_TAGS if name in commands],
            "unknown_error_lines": unknown}


def private_failure_category(output):
    """Compatibility wrapper; all detailed diagnostics remain allowlisted."""
    return private_command_diagnostics(output)["category"]


def validate_command_diagnostics(value):
    require(isinstance(value, dict) and set(value) == {"category", "returncode", "tags", "failed_commands", "unknown_error_lines"},
            "invalid_command_diagnostics")
    require(value["category"] in CATEGORY_PRIORITY, "invalid_command_diagnostics")
    require(value["returncode"] is None or type(value["returncode"]) is int, "invalid_command_diagnostics")
    for key, allowed in (("tags", TAG_CATEGORIES), ("failed_commands", FAILED_COMMAND_TAGS)):
        require(isinstance(value[key], list) and all(type(item) is str and item in allowed for item in value[key]),
                "invalid_command_diagnostics")
        require(len(value[key]) == len(set(value[key])), "invalid_command_diagnostics")
    require(type(value["unknown_error_lines"]) is int and 0 <= value["unknown_error_lines"] <= 1_000_000,
            "invalid_command_diagnostics")
    return {"category": value["category"], "returncode": value["returncode"], "tags": list(value["tags"]),
            "failed_commands": list(value["failed_commands"]), "unknown_error_lines": value["unknown_error_lines"]}


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


def base64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def archive_diagnostic_context(sha, number, run_id, attempt):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "invalid_archive_diagnostic_context")
    require(bool(re.fullmatch(r"500\.[1-9][0-9]{0,8}\.[1-9][0-9]{0,8}", number)), "invalid_archive_diagnostic_context")
    require(bool(re.fullmatch(r"[1-9][0-9]{0,17}", run_id or "")), "invalid_archive_diagnostic_context")
    require(bool(re.fullmatch(r"[1-9][0-9]{0,8}", attempt or "")) and number.rsplit(".", 1)[1] == attempt,
            "invalid_archive_diagnostic_context")
    return {"schema": ARCHIVE_DIAGNOSTIC_SCHEMA, "source_sha": sha, "build": number,
            "run_id": run_id, "run_attempt": attempt}


def archive_diagnostic_aad(context):
    return json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def load_archive_diagnostic_public_key(path):
    """Only a task-specific public RSA JWK is accepted; never read a private key."""
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8192,
                "invalid_archive_diagnostic_public_key")
        jwk = json.loads(path.read_bytes())
        require(isinstance(jwk, dict) and {"kty", "n", "e"} <= set(jwk)
                and set(jwk) <= {"kty", "n", "e", "alg", "use"}, "invalid_archive_diagnostic_public_key")
        require(jwk["kty"] == "RSA" and jwk.get("alg", "RSA-OAEP-256") == "RSA-OAEP-256"
                and jwk.get("use", "enc") == "enc", "invalid_archive_diagnostic_public_key")
        numbers = []
        for name in ("n", "e"):
            value = jwk[name]
            require(type(value) is str and bool(re.fullmatch(r"[A-Za-z0-9_-]+", value)),
                    "invalid_archive_diagnostic_public_key")
            decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            require(base64url(decoded) == value, "invalid_archive_diagnostic_public_key")
            numbers.append(int.from_bytes(decoded, "big"))
        modulus, exponent = numbers
        require(modulus.bit_length() == 4096 and exponent == 65537, "invalid_archive_diagnostic_public_key")
        key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        require(key.key_size == 4096, "invalid_archive_diagnostic_public_key")
        return key
    except Exception:
        raise ReleaseError("invalid_archive_diagnostic_public_key") from None


def encrypt_failed_archive_output(output, public_key, context, destination):
    """Encrypt one failed archive's output; no combined log or plaintext fallback."""
    temporary = None
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        require(type(output) is bytes and len(output) <= MAX_ARCHIVE_DIAGNOSTIC_RAW_BYTES,
                "archive_diagnostic_output_too_large")
        require(isinstance(public_key, rsa.RSAPublicKey) and public_key.key_size == 4096,
                "invalid_archive_diagnostic_public_key")
        require(context == archive_diagnostic_context(context["source_sha"], context["build"],
                                                       context["run_id"], context["run_attempt"]),
                "invalid_archive_diagnostic_context")
        require(not destination.exists() and not destination.parent.is_symlink(), "archive_diagnostic_destination_rejected")
        compressed = gzip.compress(output, mtime=0)
        require(len(compressed) <= MAX_ARCHIVE_DIAGNOSTIC_RAW_BYTES + 100_000, "archive_diagnostic_output_too_large")
        aad, key, nonce = archive_diagnostic_aad(context), secrets.token_bytes(32), secrets.token_bytes(12)
        envelope = {"context": context, "key_algorithm": "RSA-OAEP-256", "content_algorithm": "A256GCM",
                    "compression": "gzip", "nonce": base64url(nonce),
                    "wrapped_key": base64url(public_key.encrypt(key, padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=aad))),
                    "ciphertext": base64url(AESGCM(key).encrypt(nonce, compressed, aad))}
        payload = json.dumps(envelope, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        require(len(payload) < MAX_ARCHIVE_DIAGNOSTIC_FILE_BYTES, "archive_diagnostic_output_too_large")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(prefix="failed-archive.", dir=destination.parent)
        temporary = pathlib.Path(name)
        with os.fdopen(descriptor, "wb") as result:
            result.write(payload)
            result.flush()
            os.fsync(result.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except Exception:
        raise ReleaseError("archive_diagnostic_encryption_failed") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_archive_failure_recorder(sha, number, run_id, attempt, public_key_path, destination):
    enabled = os.environ.get("ENCRYPTED_ARCHIVE_DIAGNOSTICS", "false")
    require(enabled in ("false", "true"), "invalid_encrypted_archive_diagnostics_flag")
    if enabled == "false":
        return None
    context = archive_diagnostic_context(sha, number, run_id, attempt)
    public_key = load_archive_diagnostic_public_key(public_key_path)
    return lambda output: encrypt_failed_archive_output(output, public_key, context, destination)


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


def safe_evidence(sha, number, phase, success, uploaded, valid, cleanup_ok, command_diagnostics=None):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "invalid_evidence_sha")
    require(bool(re.fullmatch(r"500\.[1-9][0-9]{0,8}\.[1-9][0-9]{0,8}", number)), "invalid_evidence_build")
    require(phase in {"preflight", "materials", "keychain", "archive", "verify", "upload", "processing", "complete"},
            "invalid_evidence_phase")
    diagnostics = validate_command_diagnostics(command_diagnostics) if command_diagnostics is not None else None
    return {"schema_version": 2, "repository": "KANABUNN/RailVelo", "source_sha": sha,
            "bundle_id": BUNDLE_ID, "app_id": APP_ID, "version": VERSION, "build": number,
            "phase": phase, "success": bool(success), "upload_completed": bool(uploaded),
            "processing_valid_internal_only": bool(valid), "cleanup_ok": bool(cleanup_ok),
            "testers_modified": False, "profiles_generated": False, "certificates_generated": False,
            "device_acceptance": "not_verified", "command_diagnostics": diagnostics}


def runtime_paths():
    temp = pathlib.Path(os.environ["RUNNER_TEMP"]).resolve()
    return temp, temp / "railvelo-testflight-private", temp / "railvelo-testflight-state.json"


class PrivateRunner:
    def __init__(self, folder):
        self.folder = folder
        self.log = folder / "commands.log"
        self.environment = {key: value for key, value in os.environ.items() if key not in SECRET_NAMES and key != "GH_TOKEN"}

    def call(self, arguments, timeout=300, accepted=(0,), archive_failure_recorder=None):
        require(archive_failure_recorder is None or (arguments[0] == "/usr/bin/xcodebuild"
                and arguments[-1] == "archive" and "-exportArchive" not in arguments),
                "encrypted_archive_diagnostics_scope_rejected")
        with open(self.log, "ab") as log:
            os.chmod(self.log, 0o600)
            try:
                result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=self.environment, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as error:
                if archive_failure_recorder is not None and type(error.output) is bytes:
                    log.write(error.output)
                    archive_failure_recorder(error.output)
                raise PrivateCommandError("timeout") from error
            except OSError as error:
                raise PrivateCommandError("execution") from error
            log.write(result.stdout)
        if result.returncode not in accepted:
            diagnostics = private_command_diagnostics(result.stdout)
            if archive_failure_recorder is not None:
                archive_failure_recorder(result.stdout)
            raise PrivateCommandError(diagnostics["category"], result.returncode, diagnostics)
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
    command_diagnostics = None
    cleanup_ok = True
    try:
        require_export_support(runner.call(["/usr/bin/xcodebuild", "-help"]).decode(errors="replace"))
        archive_failure_recorder = prepare_archive_failure_recorder(
            sha, number, os.environ.get("GITHUB_RUN_ID"), os.environ.get("GITHUB_RUN_ATTEMPT"),
            pathlib.Path(__file__).resolve().parents[1] / "archive_diagnostics_public.json",
            temp / "railvelo-testflight-encrypted" / "failed-archive.json")
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
                     "MARKETING_VERSION=" + VERSION, "CURRENT_PROJECT_VERSION=" + number, "archive"], timeout=1200,
                    archive_failure_recorder=archive_failure_recorder)
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
        if isinstance(error, PrivateCommandError):
            command_diagnostics = error.diagnostics
    finally:
        try:
            cleanup_ok = cleanup() if state_path.exists() else True
            if not state_path.exists() and folder.exists():
                shutil.rmtree(folder)
        except BaseException:
            cleanup_ok = False
        private_write(evidence_path, (json.dumps(safe_evidence(sha, number, phase, success and cleanup_ok, uploaded, valid,
                                                            cleanup_ok, command_diagnostics), indent=2) + "\n").encode())
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

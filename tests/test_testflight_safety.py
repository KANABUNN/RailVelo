"""Offline security-boundary tests. No Apple credentials, signing, or network."""
import contextlib
import datetime as dt
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ".github/scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("testflight_gate")
release = load("testflight_release")
SHA = "a" * 40
MAIN = "b" * 40
TEAM = "TESTTEAM01"
DER = b"synthetic-certificate-only-for-structural-tests"
NOW = dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc)


def profile():
    return {"UUID": "11111111-2222-3333-4444-555555555555", "TeamIdentifier": [TEAM],
            "Platform": ["iOS"], "ExpirationDate": NOW + dt.timedelta(days=30),
            "DeveloperCertificates": [DER], "Entitlements": {
                "application-identifier": TEAM + "." + release.BUNDLE_ID,
                "com.apple.developer.team-identifier": TEAM,
                "get-task-allow": False, "beta-reports-active": True}}


def run():
    return {"id": 123, "workflow_id": 7, "head_sha": SHA, "head_branch": "main",
            "head_repository": {"full_name": gate.REPOSITORY}, "event": "push",
            "status": "completed", "conclusion": "success"}


class GitHubPrerequisites(unittest.TestCase):
    def test_only_main_manual_original_repository_accepts_full_sha(self):
        self.assertEqual(gate.validate_context(gate.REPOSITORY, "refs/heads/main", "workflow_dispatch", SHA), SHA)
        for repository, ref, event, sha in [
                ("fork/RailVelo", "refs/heads/main", "workflow_dispatch", SHA),
                (gate.REPOSITORY, "refs/heads/other", "workflow_dispatch", SHA),
                (gate.REPOSITORY, "refs/heads/main", "pull_request", SHA),
                (gate.REPOSITORY, "refs/heads/main", "workflow_dispatch", "a" * 7),
                (gate.REPOSITORY, "refs/heads/main", "workflow_dispatch", SHA + "\n"),
                (gate.REPOSITORY, "refs/heads/main", "workflow_dispatch", "$(echo injected)")]:
            with self.subTest(repository=repository, ref=ref, event=event), self.assertRaises(gate.GateError):
                gate.validate_context(repository, ref, event, sha)

    def test_ancestor_requires_status_and_exact_merge_base(self):
        value = {"status": "ahead", "merge_base_commit": {"sha": SHA}, "base_commit": {"sha": SHA}}
        gate.validate_comparison(value, SHA, MAIN)
        for bad in [{**value, "status": "diverged"}, {**value, "merge_base_commit": {"sha": MAIN}},
                    {**value, "base_commit": {"sha": MAIN}}]:
            with self.assertRaises(gate.GateError):
                gate.validate_comparison(bad, SHA, MAIN)

    def test_success_on_wrong_source_workflow_or_pr_cannot_pass(self):
        self.assertTrue(gate.qualifying_run(run(), 7, SHA))
        for change in [{"head_sha": MAIN}, {"workflow_id": 8}, {"event": "pull_request"},
                       {"head_branch": "other"}, {"status": "in_progress"}, {"conclusion": "failure"},
                       {"head_repository": {"full_name": "fork/RailVelo"}}, {"id": True}]:
            self.assertFalse(gate.qualifying_run({**run(), **change}, 7, SHA))

    def test_two_exact_workflow_successes_are_both_required(self):
        def response(url, _):
            if url.endswith("/commits/main"):
                return {"sha": MAIN}
            if "/compare/" in url:
                return {"status": "ahead", "merge_base_commit": {"sha": SHA}, "base_commit": {"sha": SHA}}
            if url.endswith("swift.yml"):
                return {"id": 7, "path": ".github/workflows/swift.yml"}
            if url.endswith("ios.yml"):
                return {"id": 8, "path": ".github/workflows/ios.yml"}
            identifier = 7 if "/workflows/7/" in url else 8
            return {"workflow_runs": [{**run(), "workflow_id": identifier, "id": identifier * 10}]}
        evidence = gate.gate(SHA, "synthetic-token", response)
        self.assertEqual((evidence["engine_run_id"], evidence["app_run_id"]), (70, 80))
        def missing(url, token):
            if "/workflows/8/runs" in url:
                return {"workflow_runs": []}
            return response(url, token)
        with self.assertRaises(gate.GateError):
            gate.gate(SHA, "synthetic-token", missing)

    def test_http_redirects_are_never_followed_with_bearer_auth(self):
        with self.assertRaises(gate.GateError):
            gate.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid")
        with self.assertRaises(release.ReleaseError):
            release.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid")


class SigningBoundaries(unittest.TestCase):
    def test_matching_unexpired_app_store_profile_passes(self):
        self.assertEqual(release.validate_profile(profile(), TEAM, DER, NOW), profile()["UUID"])

    def test_apple_ios_compatible_platforms_pass_but_other_or_unknown_platforms_fail(self):
        for platforms in [["iOS"], ["iOS", "xrOS", "visionOS"], ["iOS", "visionOS"], ["xrOS", "iOS"]]:
            with self.subTest(platforms=platforms):
                self.assertEqual(release.validate_profile({**profile(), "Platform": platforms}, TEAM, DER, NOW),
                                 profile()["UUID"])
        for platforms in [["OSX"], ["tvOS"], ["xrOS", "visionOS"], ["iOS", "OSX"], ["iOS", "tvOS"],
                          ["iOS", "futureOS"], ["iOS", None], [], "iOS", None]:
            with self.subTest(platforms=platforms), self.assertRaises(release.ReleaseError):
                release.validate_profile({**profile(), "Platform": platforms}, TEAM, DER, NOW)

    def test_ad_hoc_enterprise_debug_or_nonbeta_profile_rejected(self):
        changes = [{"ProvisionedDevices": []}, {"ProvisionedDevices": ["synthetic-device"]},
                   {"ProvisionsAllDevices": True}, {"Platform": ["OSX"]}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(release.ReleaseError):
                release.validate_profile({**profile(), **change}, TEAM, DER, NOW)
        for key, value in [("get-task-allow", True), ("get-task-allow", None), ("beta-reports-active", False)]:
            bad = profile(); bad["Entitlements"][key] = value
            with self.assertRaises(release.ReleaseError):
                release.validate_profile(bad, TEAM, DER, NOW)

    def test_wrong_team_bundle_certificate_expiration_or_uuid_rejected(self):
        bad_profiles = []
        for change in [{"TeamIdentifier": ["OTHERTEAM1"]}, {"DeveloperCertificates": [b"other"]},
                       {"ExpirationDate": NOW}, {"UUID": "../profile"}]:
            bad_profiles.append({**profile(), **change})
        for field, value in [("application-identifier", TEAM + ".other.app"),
                             ("com.apple.developer.team-identifier", "OTHERTEAM1")]:
            bad = profile(); bad["Entitlements"][field] = value; bad_profiles.append(bad)
        for bad in bad_profiles:
            with self.assertRaises(release.ReleaseError):
                release.validate_profile(bad, TEAM, DER, NOW)

    def test_signed_app_cannot_have_different_identity_or_debug_permission(self):
        entitlements = profile()["Entitlements"]
        release.validate_signed_entitlements(entitlements, TEAM)
        for change in [{"get-task-allow": True}, {"application-identifier": TEAM + ".other"},
                       {"com.apple.developer.team-identifier": "OTHERTEAM1"}]:
            with self.assertRaises(release.ReleaseError):
                release.validate_signed_entitlements({**entitlements, **change}, TEAM)

    def test_internal_only_and_exact_method_must_be_exposed_by_xcode(self):
        text = "method : String\n Available options: app-store-connect\n"
        for key, kind in [("destination", "String"), ("signingStyle", "String"), ("signingCertificate", "String"),
                          ("provisioningProfiles", "Dictionary"), ("teamID", "String"),
                          ("manageAppVersionAndBuildNumber", "Bool"), ("testFlightInternalTestingOnly", "Bool")]:
            text += key + " : " + kind + "\n description\n"
        release.require_export_support(text)
        for bad in [text.replace("testFlightInternalTestingOnly", "unknown"),
                    text.replace("Available options: app-store-connect", "Available options: debugging") + "\n unrelated app-store-connect"]:
            with self.assertRaises(release.ReleaseError):
                release.require_export_support(bad)

    def test_build_number_includes_attempt_and_rejects_command_characters(self):
        self.assertEqual(release.build_number("12", "3"), "500.12.3")
        self.assertNotEqual(release.build_number("12", "2"), release.build_number("12", "3"))
        for number, attempt in [("0", "1"), ("1", "0"), ("1;echo", "1"), ("1", "2\n"), ("1.2", "1")]:
            with self.assertRaises(release.ReleaseError):
                release.build_number(number, attempt)

    def test_private_command_output_is_captured_and_not_printed(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = release.PrivateRunner(pathlib.Path(folder))
            output = io.StringIO()
            process = subprocess.CompletedProcess(["synthetic"], 0, b"synthetic-private-output")
            with mock.patch.object(release.subprocess, "run", return_value=process), contextlib.redirect_stdout(output):
                self.assertEqual(runner.call(["synthetic"]), b"synthetic-private-output")
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(runner.log.read_bytes(), b"synthetic-private-output")

    def test_failure_categories_expose_only_allowlisted_label_and_exit_code(self):
        private = b" PRIVATE_SYNTHETIC_KEY=not-a-real-key /private/person/Profile-UUID "
        cases = [(b"No profiles for 'private.bundle' were found", "missing_profile"),
                 (b"No signing certificate 'private name' found", "signing_identity"),
                 (b"Authentication failed for private account", "authentication"),
                 (b'SDK "private-sdk-name" cannot be located.', "sdk"),
                 (b"Unable to find a destination matching the provided destination specifier", "sdk"),
                 (b"SwiftCompile normal arm64", "unknown"), (b"Swift compiler error", "compile"),
                 (b"/private/person/source.swift:12:4: error: synthetic compiler diagnostic", "compile"),
                 (b"private-target does not support provisioning profiles", "profile_target_mismatch"),
                 (b"unable to build chain to self-signed root for private certificate", "certificate_chain"),
                 (b"CSSMERR_TP_NOT_TRUSTED private certificate", "certificate_chain"),
                 (b"Asset validation failed (private value)", "upload"),
                 (b"Could not resolve host: private.example", "network"), (b"unrecognized private error", "unknown")]
        with tempfile.TemporaryDirectory() as folder:
            runner = release.PrivateRunner(pathlib.Path(folder))
            for raw, category in cases:
                with self.subTest(category=category):
                    process = subprocess.CompletedProcess(["synthetic-private-command"], 65, raw + private)
                    public = io.StringIO()
                    with mock.patch.object(release.subprocess, "run", return_value=process), \
                         contextlib.redirect_stdout(public), contextlib.redirect_stderr(public), \
                         self.assertRaises(release.PrivateCommandError) as error:
                        runner.call(["synthetic-private-command"])
                    self.assertEqual(str(error.exception),
                        "private_command_failed:category=" + category + ":returncode=65")
                    self.assertEqual(public.getvalue(), "")
                    self.assertNotIn("PRIVATE_SYNTHETIC_KEY", str(error.exception))
                    self.assertNotIn("private", error.exception.category)

    def test_signing_specific_failures_take_priority_over_generic_error_terms(self):
        for raw, expected in [
                (b"PRIVATE_TARGET does not support provisioning profiles. No profiles for PRIVATE_BUNDLE. Swift compiler error", "profile_target_mismatch"),
                (b"PRIVATE_CERT unable to build chain to self-signed root. No signing certificate. Swift compiler error", "certificate_chain"),
                (b"CSSMERR_TP_NOT_TRUSTED PRIVATE_CERT No signing certificate", "certificate_chain")]:
            self.assertEqual(release.private_failure_category(raw), expected)

    def test_compiler_activity_and_generic_failure_footers_do_not_invent_compile_errors(self):
        for raw in [b"SwiftCompile normal arm64 PRIVATE_FILE.swift", b"CompileC PRIVATE_FILE.o PRIVATE_FILE.c",
                    b"SwiftCompile normal arm64\n** ARCHIVE FAILED **", b"** BUILD FAILED **",
                    b"PRIVATE_UNKNOWN_FAILURE ** ARCHIVE FAILED **"]:
            self.assertEqual(release.private_failure_category(raw), "unknown")

    def test_timeout_and_execution_failures_do_not_copy_exception_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = release.PrivateRunner(pathlib.Path(folder))
            for original, category in [(subprocess.TimeoutExpired("PRIVATE_SYNTHETIC_COMMAND", 1,
                                       output=b"PRIVATE_SYNTHETIC_KEY"), "timeout"),
                                       (OSError("PRIVATE_SYNTHETIC_PATH"), "execution")]:
                with mock.patch.object(release.subprocess, "run", side_effect=original), \
                     self.assertRaises(release.PrivateCommandError) as error:
                    runner.call(["synthetic"])
                self.assertEqual(str(error.exception),
                    "private_command_failed:category=" + category + ":returncode=unknown")
                self.assertNotIn("PRIVATE_SYNTHETIC", str(error.exception))


class ExpandedPrivateDiagnostics(unittest.TestCase):
    def test_signing_conflict_tags_preserve_multiple_fixed_symptoms(self):
        raw = (b"error: PRIVATE_APP has conflicting provisioning settings.\n"
               b"error: PRIVATE_APP is automatically signed for development, but a profile was manually specified.\n"
               b"error: Signing PRIVATE_APP requires a development team.\n"
               b"error: The private key is not installed for PRIVATE_CERT.\n")
        details = release.private_command_diagnostics(raw)
        self.assertEqual(details["category"], "signing_configuration")
        self.assertTrue({"provisioning_settings_conflict", "development_signing_conflict",
                         "development_team_required", "private_key_missing"} <= set(details["tags"]))
        self.assertEqual(details["unknown_error_lines"], 0)
        self.assertNotIn("PRIVATE", json.dumps(details))

    def test_fixed_error_families_cover_archive_dependencies_resources_and_linking(self):
        cases = [
            (b"error: Provisioning profile PRIVATE does not match the bundle identifier PRIVATE", "profile_entitlements_mismatch", "signing_configuration"),
            (b"error: Code signing entitlements file was modified during the build PRIVATE", "entitlements_packaging_failed", "signing_configuration"),
            (b"error: Failed to register bundle identifier PRIVATE", "bundle_registration_failed", "signing_configuration"),
            (b"certificate has either expired or has been revoked PRIVATE", "certificate_expired_or_revoked", "signing_identity"),
            (b"User interaction is not allowed PRIVATE", "keychain_access_denied", "private_key"),
            (b"Undefined symbols for architecture arm64 PRIVATE", "linker_undefined_symbols", "link"),
            (b"error: duplicate symbol PRIVATE", "linker_duplicate_symbols", "link"),
            (b"ld: library not found for PRIVATE", "linker_library_missing", "link"),
            (b"error: building for iOS, but linking in object built for PRIVATE", "linker_platform_mismatch", "link"),
            (b"error: Build input file cannot be found: /private/PRIVATE", "input_file_missing", "resource"),
            (b"error: Unable to load contents of file list PRIVATE", "input_file_list_unreadable", "resource"),
            (b"error: Could not parse input file as a property list PRIVATE", "plist_invalid", "resource"),
            (b"error: None of the input catalogs contained a matching app icon set PRIVATE", "asset_catalog_app_icon_missing", "asset_catalog"),
            (b"/private/PRIVATE.xcassets: error: synthetic failure", "asset_catalog_failed", "asset_catalog"),
            (b"error: Could not resolve package dependencies PRIVATE", "package_resolution_failed", "package"),
            (b"error: Missing package product PRIVATE", "package_product_missing", "package"),
            (b"error: Failed downloading binary PRIVATE", "package_download_failed", "package"),
            (b"error: SDK PRIVATE cannot be located", "sdk_unavailable", "sdk"),
            (b"error: Not a valid archive PRIVATE", "archive_invalid", "archive"),
        ]
        for raw, tag, category in cases:
            with self.subTest(tag=tag):
                details = release.private_command_diagnostics(raw)
                self.assertIn(tag, details["tags"])
                self.assertEqual(details["category"], category)
                self.assertNotIn("PRIVATE", json.dumps(details))

    def test_explicit_failed_commands_use_only_canonical_allowlisted_names(self):
        for command in release.FAILED_COMMAND_TAGS:
            with self.subTest(command=command):
                raw = ("Command " + command + " failed with a nonzero exit code /private/PRIVATE").encode()
                details = release.private_command_diagnostics(raw)
                self.assertEqual(details["failed_commands"], [command])
                self.assertIn(release.FAILED_COMMAND_TAGS[command], details["tags"])
                self.assertNotIn("PRIVATE", json.dumps(details))

    def test_failed_summary_requires_exact_first_token_and_stops_at_footer(self):
        raw = (b"CodeSign /private/PRIVATE_SUCCESS\n"
               b"The following build commands failed:\n"
               b"    ProcessProductPackaging /private/PRIVATE_ENTITLEMENTS\n"
               b"    ValidateEmbeddedBinary /private/PRIVATE_BINARY\n"
               b"    CodeSignExtra /private/PRIVATE_UNKNOWN\n"
               b"    CodeSign:PRIVATE_ACCOUNT /private/PRIVATE_UNKNOWN\n"
               b"(4 failures)\n"
               b"SwiftCompile normal arm64 /private/PRIVATE_AFTER\n")
        details = release.private_command_diagnostics(raw)
        self.assertEqual(set(details["failed_commands"]), {"ProcessProductPackaging", "ValidateEmbeddedBinary"})
        self.assertIn("unrecognized_failed_command", details["tags"])
        self.assertEqual(details["unknown_error_lines"], 2)
        self.assertNotIn("PRIVATE", json.dumps(details))

    def test_progress_and_generic_footers_remain_unknown_and_undisclosed(self):
        raw = b"CodeSign /private/PRIVATE\nProcessProductPackaging PRIVATE\nSwiftCompile normal arm64 PRIVATE\n** ARCHIVE FAILED **"
        self.assertEqual(release.private_command_diagnostics(raw),
            {"category": "unknown", "tags": [], "failed_commands": [], "unknown_error_lines": 0})

    def test_unclassified_error_lines_and_commands_are_counted_without_copying(self):
        raw = (b"error: PRIVATE_NEW_ERROR person@private.invalid\n"
               b"Error Domain=PRIVATE_SECRET Code=999\n"
               b"Command PRIVATE_NEW_COMMAND failed with a non-zero exit code\n"
               b"** ARCHIVE FAILED **\n")
        details = release.private_command_diagnostics(raw)
        self.assertEqual(details["category"], "unknown")
        self.assertEqual(details["tags"], ["unrecognized_failed_command"])
        self.assertEqual(details["failed_commands"], [])
        self.assertEqual(details["unknown_error_lines"], 3)
        self.assertNotIn("PRIVATE", json.dumps(details))

    def test_safe_evidence_revalidates_diagnostics_and_rejects_metadata_injection(self):
        details = release.private_command_diagnostics(b"Command CodeSign failed with a nonzero exit code PRIVATE")
        error = release.PrivateCommandError(details["category"], 65, details)
        evidence = release.safe_evidence(SHA, "500.1.1", "archive", False, False, False, True, error.diagnostics)
        self.assertEqual(evidence["schema_version"], 2)
        self.assertEqual(evidence["command_diagnostics"]["failed_commands"], ["CodeSign"])
        self.assertNotIn("PRIVATE", json.dumps(evidence))
        for change in [{"category": "PRIVATE_ACCOUNT"}, {"tags": ["PRIVATE_PROFILE"]},
                       {"failed_commands": ["PRIVATE_COMMAND"]}, {"unknown_error_lines": "PRIVATE"},
                       {"unknown_error_lines": True}, {"unknown_error_lines": -1},
                       {"unknown_error_lines": 1_000_001}, {"returncode": "PRIVATE_KEY"}, {"raw": "PRIVATE_TEXT"}]:
            with self.subTest(fields=list(change)), self.assertRaisesRegex(release.ReleaseError, "invalid_command_diagnostics"):
                release.safe_evidence(SHA, "500.1.1", "archive", False, False, False, True, {**error.diagnostics, **change})

    def test_runner_keeps_raw_output_private_and_attaches_only_safe_diagnostics(self):
        raw = b"error: PRIVATE_APP has conflicting provisioning settings\nCommand ProcessProductPackagingDER failed with a nonzero exit code\nPRIVATE_KEY"
        with tempfile.TemporaryDirectory() as folder:
            runner = release.PrivateRunner(pathlib.Path(folder))
            process = subprocess.CompletedProcess(["PRIVATE_COMMAND"], 65, raw)
            public = io.StringIO()
            with mock.patch.object(release.subprocess, "run", return_value=process), \
                 contextlib.redirect_stdout(public), contextlib.redirect_stderr(public), \
                 self.assertRaises(release.PrivateCommandError) as captured:
                runner.call(["PRIVATE_COMMAND"])
            self.assertEqual(public.getvalue(), "")
            self.assertEqual(runner.log.read_bytes(), raw)
            self.assertEqual(captured.exception.diagnostics["failed_commands"], ["ProcessProductPackagingDER"])
            self.assertNotIn("PRIVATE", json.dumps(captured.exception.diagnostics))
            self.assertEqual(str(captured.exception), "private_command_failed:category=signing_configuration:returncode=65")


class AppleReadback(unittest.TestCase):
    def document(self, state="VALID", audience="INTERNAL_ONLY"):
        return {"data": [{"id": "test-build", "attributes": {"version": "500.1.1", "processingState": state,
                "buildAudienceType": audience, "expired": False}, "relationships": {
                    "app": {"data": {"id": release.APP_ID}}, "preReleaseVersion": {"data": {"id": "test-version"}}}}],
                "included": [{"type": "preReleaseVersions", "id": "test-version", "attributes": {"version": release.VERSION}},
                             {"type": "apps", "id": release.APP_ID, "attributes": {"bundleId": release.BUNDLE_ID}}]}

    def test_build_query_explicitly_includes_the_app_identity_needed_for_readback(self):
        query = release.urllib.parse.parse_qs(release.builds_path("500.1.1").split("?", 1)[1])
        self.assertEqual(set(query["include"][0].split(",")), {"preReleaseVersion", "app"})
        self.assertEqual(query["fields[apps]"], ["bundleId"])

    def test_missing_wrong_or_ambiguous_included_app_cannot_pass(self):
        for mutate in [lambda d: d["included"].pop(),
                       lambda d: d["included"][1].update(id="other-app"),
                       lambda d: d["included"][1].update(type="other-resources"),
                       lambda d: d["included"][1]["attributes"].update(bundleId="other.bundle"),
                       lambda d: d["included"][1].pop("attributes"),
                       lambda d: d["included"].append(d["included"][1])]:
            bad = self.document(); mutate(bad)
            with self.assertRaisesRegex(release.ReleaseError, "asc_included_app_mismatch"):
                release.evaluate_build(bad, "500.1.1")

    def test_valid_requires_internal_only_and_matching_app_version_build(self):
        self.assertEqual(release.evaluate_build(self.document(), "500.1.1"), "VALID")
        for bad in [self.document(audience="APP_STORE_ELIGIBLE"), self.document(state="INVALID"),
                    self.document(state="FAILED"), self.document(state="UNKNOWN")]:
            with self.assertRaises(release.ReleaseError):
                release.evaluate_build(bad, "500.1.1")
        for mutate in [lambda d: d["data"][0]["attributes"].update(version="500.1.2"),
                       lambda d: d["data"][0]["attributes"].update(expired=True),
                       lambda d: d["data"][0]["relationships"]["app"]["data"].update(id="other"),
                       lambda d: d["included"][0]["attributes"].update(version="0.4.0")]:
            bad = self.document(); mutate(bad)
            with self.assertRaises(release.ReleaseError):
                release.evaluate_build(bad, "500.1.1")

    def test_processing_and_missing_build_are_not_success(self):
        self.assertIsNone(release.evaluate_build({"data": []}, "500.1.1"))
        self.assertEqual(release.evaluate_build(self.document(state="PROCESSING"), "500.1.1"), "PROCESSING")
        bad = self.document(); bad["data"] *= 2
        with self.assertRaises(release.ReleaseError):
            release.evaluate_build(bad, "500.1.1")

    def test_safe_evidence_has_no_credentials_or_raw_values(self):
        evidence = release.safe_evidence(SHA, "500.1.1", "processing", False, True, False, True)
        self.assertFalse(evidence["processing_valid_internal_only"])
        self.assertEqual(set(evidence), {"schema_version", "repository", "source_sha", "bundle_id", "app_id", "version", "build",
            "phase", "success", "upload_completed", "processing_valid_internal_only", "cleanup_ok", "testers_modified",
            "profiles_generated", "certificates_generated", "device_acceptance", "command_diagnostics"})
        self.assertIsNone(evidence["command_diagnostics"])
        with self.assertRaises(release.ReleaseError):
            release.safe_evidence(SHA, "500.1.1", "raw-secret-output", False, False, False, True)


class CleanupBoundaries(unittest.TestCase):
    def test_failed_snapshot_update_preserves_previous_restoration_state(self):
        with tempfile.TemporaryDirectory() as location:
            path = pathlib.Path(location) / "state.json"
            before = {"profiles": [], "search_list": ["original-search"]}
            release.save_state(path, before)
            with mock.patch.object(release.os, "replace", side_effect=OSError("synthetic interruption")), \
                 self.assertRaises(OSError):
                release.save_state(path, {**before, "profiles": ["new-profile"]})
            self.assertEqual(json.loads(path.read_text()), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_cli_cleanup_returns_success_without_catching_its_own_exit(self):
        with mock.patch.object(release, "cleanup", return_value=True), \
             mock.patch.object(release, "release") as signing:
            self.assertEqual(release.main(["cleanup"]), 0)
            signing.assert_not_called()
        with mock.patch.object(release, "cleanup", return_value=False):
            self.assertEqual(release.main(["cleanup"]), 1)
        with mock.patch.object(release, "release", return_value=0):
            self.assertEqual(release.main([]), 0)

    def test_original_profile_and_keychain_search_are_restored(self):
        with tempfile.TemporaryDirectory() as location:
            temp = pathlib.Path(location)
            folder = temp / "railvelo-testflight-private"; folder.mkdir()
            profile_folder = temp / "Library/MobileDevice/Provisioning Profiles"
            profile_folder.mkdir(parents=True)
            old = profile_folder / "11111111-2222-3333-4444-555555555555.mobileprovision"
            new = profile_folder / "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.mobileprovision"
            old.write_bytes(b"temporary-replacement"); new.write_bytes(b"new-profile")
            backup = folder / "backup"; backup.write_bytes(b"original-profile")
            state_file = temp / "state.json"
            state_file.write_text(json.dumps({"folder": str(folder), "search_list": ["original-search"],
                "default_keychain": "original-default", "profiles": [
                    {"path": str(old), "backup": str(backup), "existed": True, "mode": 0o600},
                    {"path": str(new), "backup": str(folder / "no-backup"), "existed": False, "mode": 0o600}]}))
            process = subprocess.CompletedProcess(["synthetic"], 0)
            with mock.patch.object(release, "runtime_paths", return_value=(temp, folder, state_file)), \
                 mock.patch.object(release.pathlib.Path, "home", return_value=temp), \
                 mock.patch.object(release.subprocess, "run", return_value=process) as command:
                self.assertTrue(release.cleanup())
            self.assertEqual(old.read_bytes(), b"original-profile")
            self.assertFalse(new.exists()); self.assertFalse(folder.exists()); self.assertFalse(state_file.exists())
            self.assertEqual(command.call_args_list[0].args[0],
                ["/usr/bin/security", "list-keychains", "-d", "user", "-s", "original-search"])
            self.assertEqual(command.call_args_list[1].args[0],
                ["/usr/bin/security", "default-keychain", "-d", "user", "-s", "original-default"])

    def test_interruption_before_keychain_snapshot_still_removes_private_files(self):
        with tempfile.TemporaryDirectory() as location:
            temp = pathlib.Path(location); folder = temp / "railvelo-testflight-private"; folder.mkdir()
            (folder / "synthetic-private-file").write_bytes(b"synthetic-only")
            with mock.patch.object(release, "runtime_paths", return_value=(temp, folder, temp / "absent-state")):
                self.assertTrue(release.cleanup())
            self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()

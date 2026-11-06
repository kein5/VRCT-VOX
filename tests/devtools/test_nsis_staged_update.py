"""Source contracts for the Windows installer; real execution lives in installer/."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src-tauri/nsis/template.nsi").read_text(encoding="utf-8")


def block(kind, name):
    return SOURCE.split(f"\n{kind} {name}\n", 1)[1].split(f"\n{kind}End", 1)[0]


class NsisStagedUpdateTests(unittest.TestCase):
    def test_upgrade_choice_records_uninstall_and_returns(self):
        leave = block("Function", "PageLeaveReinstall")
        upgrade = leave.split('${If} $R5 == "1"', 1)[1].split("HideWindow", 1)[0]
        self.assertNotIn("ExecWait", upgrade)
        self.assertIn("Return", upgrade)
        for variable in ("deferred_kind", "deferred_uninstall", "deferred_location"):
            self.assertIn(f'StrCpy ${variable} ""', leave)
            self.assertIn(f"${variable}", upgrade)
        self.assertIn("ExecWait", leave.split("HideWindow", 1)[1])

    def test_extraction_is_staged_and_validated(self):
        install = block("Section", "Install")
        tar = next(line for line in install.splitlines() if "-xvf" in line)
        self.assertIn('-xvf "$tar_archive" -C "$tar_target"', tar)
        # tar.exe reads its arguments in the ANSI code page; pass 8.3 paths,
        # and keep the long path when the volume has none.
        prepare = install.split(tar, 1)[0].rsplit('DetailPrint "Extracting', 1)[1]
        for variable, path in (("tar_archive", "$TEMP\\$file_name"), ("tar_target", "$INSTDIR\\.upd\\new")):
            self.assertIn(f'GetFullPathName /SHORT ${variable} "{path}"', prepare)
            self.assertIn(f'${{IfThen}} ${variable} == "" ${{|}} StrCpy ${variable} "{path}" ${{|}}', prepare)
        validated = install.split(tar, 1)[1].split("attempt_failed:", 1)[0]
        self.assertIn('${If} $0 == 0', validated)
        self.assertIn('${FileExists} "$INSTDIR\\.upd\\new\\${MAINBINARYNAME}.exe"', validated)
        self.assertIn('${FileExists} "$INSTDIR\\.upd\\new\\_internal\\*.*"', validated)
        self.assertEqual(install.count("Call CheckAppIsRunning"), 2)
        self.assertNotIn("!insertmacro CheckIfAppIsRunning", install)

    def test_transaction_renames_check_errors(self):
        for name in ("CommitStagedEntry", "RollbackInstall", "DiscardInstalledEntry"):
            code = block("Function", name)
            self.assertRegex(code, r"(?m)^\s*Rename ")
            for match in re.finditer(r"(?m)^\s*Rename [^\n]+\n([^\n]+)", code):
                self.assertRegex(match[1], r"^\s*IfErrors ")
        install = block("Section", "Install")
        commit = install.split("install_ready:", 1)[1]
        for match in re.finditer(r"(?m)^\s*Rename [^\n]+\n([^\n]+)", commit):
            self.assertRegex(match[1], r"^\s*IfErrors ")
        self.assertRegex(commit, r'WriteUninstaller [^\n]+\n\s*IfErrors commit_failed')
        self.assertIn('FileOpen $0 "$INSTDIR\\.upd\\add\\uninstall.exe" w', commit)
        self.assertLess(commit.index('StrCpy $upd_entry "${MAINBINARYNAME}.exe"'),
                        commit.index("commit_next:"))

    def test_marker_precedes_mutations_and_is_removed_before_cleanup(self):
        install = block("Section", "Install")
        commit = install.split("install_ready:", 1)[1]
        self.assertLess(commit.index('"$INSTDIR\\.upd\\committing" w'), commit.index("Rename "))
        for code in (commit, block("Function", "RollbackInstall")):
            self.assertLess(code.index('Delete "$INSTDIR\\.upd\\committing"'),
                            code.index('RMDir /r "$INSTDIR\\.upd"'))
        rollback = block("Function", "RollbackInstall")
        failure = rollback.split("rollback_failed:", 1)[1]
        self.assertNotIn("RMDir", failure)
        self.assertNotIn("Delete", failure)

    def test_enumeration_closes_before_mutation(self):
        enum = block("Function", "FirstUpdateEntry")
        self.assertIn("FindFirst", enum)
        self.assertIn("FindClose", enum)
        self.assertNotIn("Rename", enum)
        for name in ("CommitStagedEntry", "RollbackInstall", "DiscardInstalledEntry"):
            self.assertNotIn("FindFirst", block("Function", name))

    def test_cleanup_retries_rollback_and_preserves_failed_restore(self):
        cleanup = block("Function", "CleanupFailedInstall")
        self.assertIn("Call CleanupFailedInstall", block("Function", ".onInstFailed"))
        self.assertIn("Call RollbackInstall", cleanup)
        self.assertIn('${IfThen} $upd_failed == "1" ${|} Return ${|}', cleanup)
        self.assertNotIn('Delete "$INSTDIR', cleanup)
        self.assertIn('RMDir "$INSTDIR"', cleanup)
        self.assertIn('RmDir /r "$INSTDIR\\.upd"', block("Section", "Uninstall"))

    def test_package_transfers_stop_before_file_reuse(self):
        http = [line for line in SOURCE.splitlines() if "NScurl::http" in line]
        self.assertEqual(len(http), 6)
        for line in http:
            self.assertIn('/TAG "package"', line)
        stop = block("Function", "StopPackageTransfers")
        self.assertLess(stop.index("NScurl::cancel"), stop.index("NScurl::wait"))
        self.assertIn('/TAG "package"', stop)
        install = block("Section", "Install")
        for label in ("install_attempt:", "attempt_failed:"):
            first = install.split(label, 1)[1].strip().splitlines()[0]
            self.assertEqual(first, "Call StopPackageTransfers")
        cleanup = block("Function", "CleanupFailedInstall")
        self.assertLess(cleanup.index("Call StopPackageTransfers"), cleanup.index("Delete "))

    def test_deferred_uninstall_order_and_location_guard(self):
        install = block("Section", "Install")
        commit = install.split("install_ready:", 1)[1]
        self.assertLess(commit.index('$deferred_kind == "wix"'), commit.index("WriteUninstaller"))
        self.assertLess(commit.index("WriteUninstaller"), commit.index('$deferred_kind == "nsis"'))
        self.assertLess(commit.index('$deferred_kind == "nsis"'), commit.index("WriteRegStr"))
        self.assertIn('${AndIf} $deferred_location != $INSTDIR', commit)
        # An unknown location could be $INSTDIR, where UninstallString now names
        # the uninstaller just written; running it would delete the new app.
        self.assertIn('${AndIf} $deferred_location != ""', commit)
        self.assertIn('${AndIf} $deferred_uninstall != ""', commit)
        self.assertIn('/P _?=$deferred_location', commit)
        # If retiring the marker fails, rollback must precede irreversible
        # old-location removal and registry changes.
        self.assertLess(commit.index('Delete "$INSTDIR\\.upd\\committing"'),
                        commit.index('$deferred_kind == "nsis"'))


class NsisAppProcessAndDataTests(unittest.TestCase):
    def test_running_check_also_stops_the_sidecar(self):
        conf = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        sidecar = Path(conf["bundle"]["externalBin"][0]).name
        self.assertIn(f'!define SIDECARBINARYNAME "{sidecar}"', SOURCE)
        macro = SOURCE.split("\n!macro CheckIfAppIsRunning\n", 1)[1].split("\n!macroend", 1)[0]
        # Killing vrct-vox.exe skips the shell plugin's exit handler, which
        # is what normally stops the sidecar.
        after_app = macro.split("app_check_done:", 1)[1]
        for call in ("FindProcessCurrentUser", "KillProcessCurrentUser", "FindProcess", "KillProcess"):
            self.assertIn(f'nsis_tauri_utils::{call} "${{SIDECARBINARYNAME}}.exe"', after_app)
        self.assertIn('Abort "$(failedToKillApp)"', after_app)
        uninstall = block("Section", "Uninstall")
        self.assertLess(uninstall.index("!insertmacro CheckIfAppIsRunning"), uninstall.index("Delete "))

    def test_no_components_page(self):
        # Every section is required; the page let users skip the app or WebView2.
        code = [line for line in SOURCE.splitlines() if not line.lstrip().startswith(";")]
        self.assertFalse([line for line in code if "MUI_PAGE_COMPONENTS" in line])

    def test_delete_app_data_covers_state_next_to_config(self):
        uninstall = block("Section", "Uninstall")
        opted_in = uninstall.split("${If} $DeleteAppDataCheckboxState == 1", 1)[1].split("${EndIf}", 1)[0]
        for line in ('RmDir /r "$INSTDIR\\downloaded_models"', 'Delete "$INSTDIR\\voice_mute_state.json"',
                     'Delete "$INSTDIR\\config.json"', 'RmDir /r "$INSTDIR\\weights"'):
            self.assertIn(line, opted_in)
            # Kept when the box is not ticked, e.g. when an update moves the install.
            self.assertEqual(uninstall.count(line), 1)


if __name__ == "__main__":
    unittest.main()

"""Source contracts for the Windows transaction; real execution lives in installer/."""

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
        self.assertIn('-C "$INSTDIR\\.upd\\new"', tar)
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


if __name__ == "__main__":
    unittest.main()

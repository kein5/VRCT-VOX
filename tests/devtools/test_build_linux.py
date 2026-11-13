"""Offline dependency-verification contracts; never install or build packages."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import build_linux
from tools.check_python_lock import validate_lock


SHA256 = 'a' * 64
COMMIT = 'b' * 40
INDEX_PACKAGE = f'''
[[package]]
name = "example"
version = "1.2.3"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "https://example.invalid/example-1.2.3.tar.gz", hash = "sha256:{SHA256}" }}
wheels = [{{ url = "https://example.invalid/example-1.2.3-py3-none-any.whl", hash = "sha256:{SHA256}" }}]
'''
GIT_PACKAGE = f'''
[[package]]
name = "git-example"
version = "2.0.0"
source = {{ git = "https://example.invalid/source?rev={COMMIT}#{COMMIT}" }}
'''
PROJECT = '''
[[package]]
name = "vrct-vox"
version = "0.1.0"
source = { virtual = "." }
'''


class LinuxDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vox build hashes ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lock = self.root / 'uv.lock'
        self.write_lock(INDEX_PACKAGE + GIT_PACKAGE + PROJECT)

    def write_lock(self, packages):
        self.lock.write_text('version = 1\nrevision = 5\nrequires-python = "==3.11.*"\n' + packages,
                             encoding='utf-8')

    def test_valid_archives_git_and_uninstalled_root_are_accepted(self):
        validate_lock(self.lock)

    def test_repository_lock_is_verifiable(self):
        validate_lock(build_linux.ROOT / 'uv.lock')

    def test_git_requires_full_sha_in_both_requested_and_resolved_revision(self):
        for requested, resolved in (
            ('main', COMMIT), (COMMIT[:7], COMMIT), (COMMIT, COMMIT[:7]),
            (COMMIT, 'main'), (COMMIT, 'c' * 40), ('g' * 40, 'g' * 40),
        ):
            with self.subTest(requested=requested, resolved=resolved):
                self.write_lock(GIT_PACKAGE.replace(f'rev={COMMIT}#{COMMIT}', f'rev={requested}#{resolved}'))
                with self.assertRaisesRegex(ValueError, 'git-example.*full 40-character commit SHA'):
                    validate_lock(self.lock)

    def test_git_tag_or_branch_is_rejected_even_with_resolved_commit(self):
        for query in ('tag=v2', 'branch=main', ''):
            with self.subTest(query=query):
                self.write_lock(GIT_PACKAGE.replace(f'rev={COMMIT}', query))
                with self.assertRaisesRegex(ValueError, 'full 40-character commit SHA'):
                    validate_lock(self.lock)

    def test_non_vcs_package_without_any_archive_hash_is_rejected(self):
        self.write_lock(INDEX_PACKAGE.replace(f', hash = "sha256:{SHA256}"', ''))
        with self.assertRaisesRegex(ValueError, 'example 1.2.3.*missing or invalid SHA-256'):
            validate_lock(self.lock)

    def test_every_archive_needs_a_valid_hash_even_when_another_has_one(self):
        for checksum in ('', 'sha256:1234', 'sha256:' + 'g' * 64, 'md5:' + 'a' * 32):
            with self.subTest(checksum=checksum):
                self.write_lock(INDEX_PACKAGE.replace(f'sha256:{SHA256}', checksum, 1))
                with self.assertRaisesRegex(ValueError, 'example-1.2.3.tar.gz'):
                    validate_lock(self.lock)

    def test_non_vcs_package_without_artifacts_is_rejected(self):
        self.write_lock(INDEX_PACKAGE.split('sdist =')[0])
        with self.assertRaisesRegex(ValueError, 'non-VCS package has no hashed archives'):
            validate_lock(self.lock)

    def test_local_sources_cannot_bypass_hash_validation(self):
        for source in ('{ directory = "../local" }', '{ editable = "../local" }',
                       '{ virtual = "." }', '{ path = "local.whl" }'):
            with self.subTest(source=source):
                self.write_lock(INDEX_PACKAGE.replace('{ registry = "https://pypi.org/simple" }', source))
                with self.assertRaisesRegex(ValueError, 'unsupported non-VCS source'):
                    validate_lock(self.lock)

    def test_direct_archive_url_still_requires_hashes(self):
        package = INDEX_PACKAGE.replace('registry = "https://pypi.org/simple"',
                                        'url = "https://example.invalid/example-1.2.3.tar.gz"')
        self.write_lock(package)
        validate_lock(self.lock)
        self.write_lock(package.replace(f', hash = "sha256:{SHA256}"', ''))
        with self.assertRaisesRegex(ValueError, 'missing or invalid SHA-256'):
            validate_lock(self.lock)

    def test_sync_uses_hashed_lock_and_same_groups_in_explicit_build_environment(self):
        venv = self.root / 'build with spaces/venv'
        with patch.object(build_linux, 'ROOT', self.root), patch.object(build_linux, 'run') as run, \
                patch.dict(os.environ, {'UV_PROJECT_ENVIRONMENT': '/wrong/environment'}):
            build_linux.sync_dependencies(['uv', '--offline'], venv, '3.11')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ['uv', '--offline', 'venv', '--python', '3.11', venv])
        command = run.call_args.args[0]
        self.assertEqual(command, ['uv', '--offline', 'sync', '--frozen', '--no-install-project',
                                   '--python', venv / 'bin/python', '--group', 'dev', '--group', 'linux-build'])
        self.assertEqual(run.call_args.kwargs['cwd'], self.root)
        self.assertEqual(run.call_args.kwargs['env']['UV_PROJECT_ENVIRONMENT'], str(venv.resolve()))
        # uv consumes uv.lock itself; hashes and full commits are never stripped
        # or passed through a second dependency resolver.
        self.assertIn(f'hash = "sha256:{SHA256}"', self.lock.read_text())
        self.assertIn(f'rev={COMMIT}#{COMMIT}', self.lock.read_text())
        self.assertFalse((self.root / 'requirements.txt').exists())

    def test_invalid_lock_stops_before_any_environment_command(self):
        for packages in (INDEX_PACKAGE.replace(f', hash = "sha256:{SHA256}"', ''),
                         GIT_PACKAGE.replace(COMMIT, 'main')):
            with self.subTest(packages=packages):
                self.write_lock(packages)
                with patch.object(build_linux, 'ROOT', self.root), patch.object(build_linux, 'run') as run:
                    with self.assertRaises(ValueError):
                        build_linux.sync_dependencies(['uv'], self.root / 'venv', '3.11')
                run.assert_not_called()

    def test_installer_hash_failure_aborts_build_before_freezing(self):
        commands = []

        def subprocess_run(argv, **kwargs):
            self.assertTrue(kwargs['check'])
            commands.append(argv)
            if argv[:2] == ['uv', 'sync']:
                raise subprocess.CalledProcessError(1, argv, stderr='Hash mismatch')

        with patch.object(build_linux, 'ROOT', self.root), \
                patch.object(build_linux.sys, 'platform', 'linux'), \
                patch.object(build_linux.platform, 'machine', return_value='x86_64'), \
                patch.object(sys, 'argv', ['build_linux.py', '--work-dir', str(self.root / 'build'),
                                          '--speech-archive', str(self.root / 'speech.zip')]), \
                patch.object(build_linux.subprocess, 'run', side_effect=subprocess_run), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                build_linux.main()
        self.assertEqual([command[:2] for command in commands], [['uv', 'venv'], ['uv', 'sync']])
        self.assertFalse((self.root / 'build/resources').exists())

    def test_validator_cli_reports_bad_lock_and_exits_nonzero(self):
        self.write_lock(GIT_PACKAGE.replace(COMMIT, 'main'))
        result = subprocess.run([sys.executable, '-S', str(build_linux.ROOT / 'tools/check_python_lock.py'),
                                 str(self.lock)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Python dependency verification failed:', result.stderr)
        self.assertIn('git-example', result.stderr)


if __name__ == '__main__':
    unittest.main()

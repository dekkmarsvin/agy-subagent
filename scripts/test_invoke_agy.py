import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('bridge', Path(__file__).with_name('invoke_agy.py'))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def invoke(self, raw=None, process_code=0, timeout=False, existing=False, empty=False, gate=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / 'prompt.txt'
            text = '' if empty else '繁體中文 "quoted"\n$(Write-Output BAD); `literal`'
            prompt.write_text(text, encoding='utf-8')
            run = root / 'run'
            if existing:
                run.mkdir()
                (run / 'keep.txt').write_text('preserve')
            process = Mock(pid=987654, returncode=process_code)
            process.poll.return_value = 0
            if timeout:
                process.wait.side_effect = [subprocess.TimeoutExpired('agy', 1), 0]
            captured = {}
            def spawn(command, **kwargs):
                captured['command'] = command
                captured['kwargs'] = kwargs
                kwargs['stdout'].write((raw or '').encode('utf-8'))
                return process
            argv = ['bridge', '--cwd', str(root), '--prompt-file', str(prompt), '--run-dir', str(run), '--timeout', '1']
            default_gate = ('gemini-3.8-flash-high', {'status': 'ALLOWED', 'remaining_percent': 100})
            gate_kwargs = {'side_effect': gate} if isinstance(gate, Exception) else {'return_value': gate or default_gate}
            with patch.object(sys, 'argv', argv), patch.object(bridge.shutil, 'which', return_value='agy.exe'), patch.object(bridge, 'prepare_dispatch', **gate_kwargs), patch.object(bridge.subprocess, 'Popen', side_effect=spawn) as start, patch.object(bridge.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()) as output:
                code = bridge.main()
            payload = json.loads(output.getvalue())
            if existing:
                self.assertEqual((run / 'keep.txt').read_text(), 'preserve')
            if existing or empty or gate is not None:
                start.assert_not_called()
            if not existing and not empty:
                self.assertEqual(json.loads((run / 'result.json').read_text(encoding='utf-8')), payload)
            return code, payload, captured, text

    def test_literal_unicode_prompt_and_success(self):
        code, result, call, text = self.invoke(json.dumps({'status': 'SUCCESS', 'conversation_id': 'one', 'response': '完成'}))
        self.assertEqual(code, 0)
        self.assertEqual(result['response'], '完成')
        self.assertEqual(call['command'][call['command'].index('--print') + 1], text)
        self.assertNotIn('shell', call['kwargs'])
        self.assertEqual(call['kwargs']['stdin'], subprocess.DEVNULL)
        self.assertEqual(call['command'][call['command'].index('--model') + 1], 'gemini-3.8-flash-high')

    def test_low_quota_prevents_process_creation(self):
        code, result, *_ = self.invoke(gate=('gemini-3.8-flash-high', {'status': 'BLOCKED_QUOTA', 'remaining_percent': 14.99}))
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED_QUOTA')

    def test_unknown_quota_prevents_process_creation(self):
        code, result, *_ = self.invoke(gate=bridge.QuotaError('quota unavailable'))
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'QUOTA_UNAVAILABLE')

    def test_invalid_json(self):
        self.assertEqual(self.invoke('not-json')[0], 1)

    def test_agent_failure(self):
        self.assertEqual(self.invoke('{"status":"ERROR"}')[0], 1)

    def test_nonzero_exit_even_success_payload(self):
        self.assertEqual(self.invoke('{"status":"SUCCESS","response":"ok","conversation_id":"one"}', process_code=3)[0], 1)

    def test_incomplete_success(self):
        self.assertEqual(self.invoke('{"status":"SUCCESS","response":"ok"}')[0], 1)

    def test_timeout(self):
        code, result, *_ = self.invoke(timeout=True)
        self.assertEqual(code, 124)
        self.assertEqual(result['status'], 'TIMEOUT')

    def test_denied_actions_fail_closed(self):
        self.assertEqual(self.invoke('{"status":"SUCCESS","response":"done","conversation_id":"one","denied_actions":[{"action":"read_file"}]}')[0], 1)

    def test_empty_response_is_not_success(self):
        self.assertEqual(self.invoke('{"status":"SUCCESS","response":"","conversation_id":"one"}')[0], 1)

    def test_existing_run_not_overwritten(self):
        self.assertEqual(self.invoke(existing=True)[0], 1)

    def test_empty_prompt_not_dispatched(self):
        self.assertEqual(self.invoke(empty=True)[0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

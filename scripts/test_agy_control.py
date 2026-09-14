import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import agy_control as control


def usage(gemini=1, third_party=1):
    return {'status': 'SUCCESS', 'command': {'name': 'usage', 'data': {'groups': [
        {'name': 'Gemini Models', 'buckets': [
            {'id': 'gemini-weekly', 'window': 'weekly', 'remaining_fraction': 0.01},
            {'id': 'gemini-5h', 'window': '5h', 'remaining_fraction': gemini}]},
        {'name': 'Claude and GPT models', 'buckets': [
            {'id': '3p-5h', 'window': '5h', 'remaining_fraction': third_party}]}]}}}


class ControlTests(unittest.TestCase):
    def test_boundary(self):
        for value, expected in [(0, 'BLOCKED_QUOTA'), (0.14999, 'BLOCKED_QUOTA'), (0.15, 'ALLOWED'), (1, 'ALLOWED')]:
            with self.subTest(value=value):
                self.assertEqual(control.evaluate_quota(usage(value), control.DEFAULT_MODEL)['status'], expected)

    def test_selected_group_only(self):
        self.assertEqual(control.evaluate_quota(usage(0.8, 0.1), control.DEFAULT_MODEL)['status'], 'ALLOWED')
        for model in ['claude-sonnet-4-6', 'gpt-oss-120b-medium']:
            self.assertEqual(control.evaluate_quota(usage(0.8, 0.1), model)['status'], 'BLOCKED_QUOTA')

    def test_invalid_fraction_fails_closed(self):
        for value in [None, '0.5', True, -0.1, 1.1, float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(control.QuotaError):
                control.evaluate_quota(usage(value), control.DEFAULT_MODEL)

    def test_bad_schema_and_unknown_model(self):
        for payload in [None, {}, {'status': 'ERROR'}, {'status': 'SUCCESS', 'command': {'name': 'model'}}]:
            with self.subTest(payload=payload), self.assertRaises(control.QuotaError):
                control.evaluate_quota(payload, control.DEFAULT_MODEL)
        with self.assertRaises(control.QuotaError):
            control.evaluate_quota(usage(), 'new-provider-model')

    def test_missing_duplicate_or_wrong_window(self):
        for mode in ['missing', 'duplicate', 'wrong-window']:
            payload = usage()
            buckets = payload['command']['data']['groups'][0]['buckets']
            if mode == 'missing':
                buckets.pop()
            elif mode == 'duplicate':
                buckets.append(dict(buckets[-1]))
            else:
                buckets[-1]['window'] = 'weekly'
            with self.subTest(mode=mode), self.assertRaises(control.QuotaError):
                control.evaluate_quota(payload, control.DEFAULT_MODEL)

    def test_live_query_failure(self):
        for error in [ValueError('invalid json'), subprocess.TimeoutExpired('agy', 30)]:
            with patch.object(control, 'run_cli', side_effect=error), self.assertRaises(control.QuotaError):
                control.check_quota(control.DEFAULT_MODEL)

    def test_each_check_queries_fresh_quota(self):
        with patch.object(control, 'run_cli', side_effect=[json.dumps(usage(0.5)), json.dumps(usage(0.1))]) as query:
            self.assertEqual(control.check_quota(control.DEFAULT_MODEL)['status'], 'ALLOWED')
            self.assertEqual(control.check_quota(control.DEFAULT_MODEL)['status'], 'BLOCKED_QUOTA')
            self.assertEqual(query.call_count, 2)

    def test_live_model_catalog_parsing(self):
        with patch.object(control, 'run_cli', return_value='Fetching available models...\ngemini-3.8-flash-high\tGemini 3.8 Flash (High)\n'):
            self.assertEqual(control.list_models(), [{'id': control.DEFAULT_MODEL, 'label': 'Gemini 3.8 Flash (High)'}])

    def test_empty_or_duplicate_catalog(self):
        for value in ['', 'x\tX\nx\tX\n']:
            with patch.object(control, 'run_cli', return_value=value), self.assertRaises(ValueError):
                control.list_models()

    def test_persist_selection_and_override(self):
        models = [{'id': control.DEFAULT_MODEL}, {'id': 'claude-sonnet-4-6'}]
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'SETTINGS', Path(directory) / 'settings.local.json'), patch.object(control, 'list_models', return_value=models):
            self.assertEqual(control.selected_model(), control.DEFAULT_MODEL)
            with patch.object(sys, 'argv', ['control', 'select', 'claude-sonnet-4-6']), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(control.main(), 0)
            self.assertEqual(control.selected_model(), 'claude-sonnet-4-6')
            with patch.object(control, 'check_quota', return_value={'status': 'ALLOWED'}):
                self.assertEqual(control.prepare_dispatch(control.DEFAULT_MODEL)[0], control.DEFAULT_MODEL)
            self.assertEqual(control.selected_model(), 'claude-sonnet-4-6')

    def test_invalid_selection_preserves_setting(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'SETTINGS', Path(directory) / 'settings.local.json'), patch.object(control, 'list_models', return_value=[{'id': control.DEFAULT_MODEL}]):
            with patch.object(sys, 'argv', ['control', 'select', 'invalid']), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(control.main(), 1)
            self.assertFalse(control.SETTINGS.exists())

    def test_interactive_selector(self):
        models = [{'id': control.DEFAULT_MODEL, 'label': 'Gemini'}, {'id': 'claude-sonnet-4-6', 'label': 'Claude'}]
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'SETTINGS', Path(directory) / 'settings.local.json'), patch.object(control, 'list_models', return_value=models), patch.object(sys, 'argv', ['control', 'select']), patch.object(sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='2'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(control.main(), 0)
            self.assertEqual(control.selected_model(), 'claude-sonnet-4-6')


if __name__ == '__main__':
    unittest.main(verbosity=2)

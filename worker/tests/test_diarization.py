"""Contract tests; run with PYTHONPATH=worker python -m unittest discover -s worker/tests."""
import json
import os
import types
import unittest
from unittest.mock import patch
import numpy as np
from pipeline import diarization

class DiarizationContractTests(unittest.TestCase):
    def test_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(diarization.backend_name(), 'nemotron')
    def test_rollback(self):
        with patch.dict(os.environ, {'DIARIZATION_BACKEND':'pyannote'}, clear=True):
            self.assertEqual(diarization.backend_name(), 'pyannote')
    def test_invalid_backend(self):
        with patch.dict(os.environ, {'DIARIZATION_BACKEND':'typo'}, clear=True):
            with self.assertRaises(ValueError): diarization.backend_name()
    def test_empty(self):
        self.assertEqual(diarization.diarize_segments(np.zeros(0)), [])
    def test_mono_required(self):
        with self.assertRaises(ValueError): diarization.diarize_segments(np.zeros((2,16000)))
    def test_dataframe_contract_and_temp_cleanup(self):
        segments=[{'start':.1,'end':.9,'speaker':'SPEAKER_0'}]
        seen=[]
        def fake_run(args, **kwargs):
            path=args[args.index('--audio')+1]
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(np.load(path,allow_pickle=False).shape,(16000,))
            seen.append(path)
            return types.SimpleNamespace(returncode=0,stdout=json.dumps(segments),stderr='')
        with patch.dict(os.environ,{'DIARIZATION_BACKEND':'nemotron'}), patch.object(diarization.subprocess,'run',side_effect=fake_run):
            frame=diarization.diarize_dataframe(np.zeros(16000))
        self.assertEqual(list(frame.columns),['start','end','speaker'])
        self.assertEqual(frame.to_dict('records'),segments)
        self.assertFalse(os.path.exists(seen[0]))
    def test_child_failure_is_not_silent_fallback(self):
        failed=types.SimpleNamespace(returncode=1,stdout='',stderr='failed')
        with patch.dict(os.environ,{'DIARIZATION_BACKEND':'nemotron'}), patch.object(diarization.subprocess,'run',return_value=failed):
            with self.assertRaisesRegex(RuntimeError,'Nemotron diarization failed'):
                diarization.diarize_segments(np.zeros(16000))
    def test_invalid_bounds(self):
        bad=types.SimpleNamespace(returncode=0,stdout=json.dumps([{'start':0,'end':10,'speaker':'SPEAKER_0'}]),stderr='')
        with patch.dict(os.environ,{'DIARIZATION_BACKEND':'nemotron'}), patch.object(diarization.subprocess,'run',return_value=bad):
            with self.assertRaisesRegex(RuntimeError,'bounds'): diarization.diarize_segments(np.zeros(16000))

if __name__=='__main__': unittest.main()

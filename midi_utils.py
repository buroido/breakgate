# midi_utils.py
import time
import pygame.midi

def _safe_midi_init():
    # pygame.midi.init() は複数回呼んでもOKだが軽くガード
    if not pygame.midi.get_init():
        pygame.midi.init()

def list_midi_output_devices():
    _safe_midi_init()
    n = pygame.midi.get_count()
    devices = []
    for i in range(n):
        info = pygame.midi.get_device_info(i)
        if not info:
            continue
        interf, name, is_input, is_output, opened = info
        if is_output:
            devices.append((i, name.decode(errors="ignore")))
    return devices

def pick_default_midi_out_id(prefer_names=("Microsoft GS Wavetable", "MIDI", "Synth")) -> int:
    """候補名を優先して出力デバイスIDを選ぶ。無ければ先頭。無ければ -1。"""
    outs = list_midi_output_devices()
    if not outs:
        return -1
    for pid, pname in outs:
        if any(s.lower() in pname.lower() for s in prefer_names):
            return pid
    return outs[0][0]

def open_output_or_none(device_id: int = None):
    """Output を開いて返す（失敗時 None）。device_id=None なら pick→デフォルトの順で選ぶ。"""
    try:
        _safe_midi_init()
        if device_id is None or device_id == -1:
            device_id = pick_default_midi_out_id()
            if device_id == -1:
                device_id = pygame.midi.get_default_output_id()
        if device_id is None or device_id == -1:
            return None
        return pygame.midi.Output(device_id)
    except Exception:
        return None

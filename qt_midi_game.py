import sys
import time
import random
import threading
import os
from collections import defaultdict
from midi_utils import list_midi_output_devices, pick_default_midi_out_id, open_output_or_none

from xplatform_window import (
    activate_for_input,
    show_fullscreen_borderless,
    make_click_through,
)

import mido
import pygame
import pygame.midi

from PyQt5.QtWidgets import (
    QApplication, QWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QPushButton, QFileDialog,QVBoxLayout,QGraphicsLineItem
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QPen
# qt_midi_game.py
try:
    from midi_utils import pick_default_midi_out_id, open_output_or_none
except ImportError:
    import pygame.midi
    def _safe_midi_init():
        if not pygame.midi.get_init():
            pygame.midi.init()
    def pick_default_midi_out_id(prefer_names=("Microsoft GS Wavetable","MIDI","Synth")):
        _safe_midi_init()
        n = pygame.midi.get_count()
        outs = []
        for i in range(n):
            info = pygame.midi.get_device_info(i)
            if info and info[3]:  # is_output
                outs.append((i, info[1].decode(errors="ignore")))
        if not outs: return -1
        for pid, pname in outs:
            if any(s.lower() in pname.lower() for s in prefer_names):
                return pid
        return outs[0][0]
    def open_output_or_none(device_id=None):
        _safe_midi_init()
        try:
            if device_id is None or device_id == -1:
                device_id = pick_default_midi_out_id()
                if device_id == -1:
                    device_id = pygame.midi.get_default_output_id()
            if device_id is None or device_id == -1:
                return None
            return pygame.midi.Output(device_id)
        except Exception:
            return None


# ====== デバッグ用：テストMIDI固定パス ======
TEST_MIDI_PATH = r"C:\Users\tubasa usami\pythoncode\pomodoro\music\45秒で何ができる.mid"

# ====== 表示系の定数 ======
# 先頭の定数を少し整理
# ====== 表示系の定数（置き換え） ======
FIELD_W, FIELD_H = 720, 960        # フィールドの論理サイズ（好きな比率でOK）
LANES = 4
LANE_W = FIELD_W / LANES
JUDGE_Y = int(FIELD_H * 0.83)      # 判定ライン（下寄り）
NOTE_W, NOTE_H = 100, 20
NOTE_SPEED = 300.0
JUST_PX = 10
GOOD_PX = 30
AUDIO_DELAY = max((JUDGE_Y - NOTE_H/2) / NOTE_SPEED, 0.0)
def _win_force_topmost(widget, on=True):
    # モジュール内に小さなWin32ヘルパを持たせる
    try:
        import ctypes, sys
        if sys.platform != "win32":
            return
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        SWP_NOMOVE=0x2; SWP_NOSIZE=0x1; SWP_NOACTIVATE=0x10; SWP_SHOWWINDOW=0x40
        HWND_TOPMOST=-1; HWND_NOTOPMOST=-2
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST if on else HWND_NOTOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
    except Exception:
        pass


class NoteItem(QGraphicsRectItem):
    def __init__(self, start_time, column, width, height):
        super().__init__(-width/2, -height/2, width, height)
        self.start_time = start_time  # 秒
        self.column = column          # 0..3
        self.hit = False

from PyQt5.QtGui import QBrush, QColor, QFont, QPen, QPainter

class MidiGame(QWidget):
    def __init__(self, midi_path, preview_mode=False, difficulty="Normal",midi_out_id=None):
        super().__init__()
        self.setWindowTitle("PyQt MIDI Game")

        self.preview_mode = preview_mode
        self.difficulty = difficulty
        self.font = QFont("Arial", 18)

        # --- Scene / View ---
        self.scene = QGraphicsScene(0, 0, FIELD_W, FIELD_H)
        self.view = QGraphicsView(self.scene, self)
        self.view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.setFocusPolicy(Qt.StrongFocus)
        self.view.setBackgroundBrush(QBrush(QColor(255, 255, 255)))  # ← 余白は白
        self.view.setAlignment(Qt.AlignCenter)                       # ← 中央寄せ
        self.view.setRenderHint(QPainter.Antialiasing, False)        # くっきり
        
            # ★ これを追加：ウィンドウいっぱいに View を広げる
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view)

        # ここがポイント：フィールド用のルート
        self.field_root = QGraphicsRectItem(0, 0, FIELD_W, FIELD_H)
        self.field_root.setPen(QPen(Qt.NoPen))
        self.field_root.setBrush(QBrush(QColor(255, 255, 255, 240)))  # 薄い白
        self.scene.addItem(self.field_root)

        # 判定ライン・レーン線（FIELD_H をフルに使う）
        # 判定ライン・レーン線
        pen = QPen(QColor(0, 0, 0)); pen.setWidth(2)
        jl = self.scene.addLine(0, JUDGE_Y, FIELD_W, JUDGE_Y, pen)
        jl.setParentItem(self.field_root)

        grid_pen = QPen(QColor(80, 80, 80)); grid_pen.setWidth(1)
        for i in range(LANES + 1):
            x = i * LANE_W
            gl = self.scene.addLine(x, 0, x, FIELD_H, grid_pen)
            gl.setParentItem(self.field_root)


        # スコア UI（フィールド内の固定座標）
        self.combo = 0; self.just = 0; self.good = 0; self.miss = 0
        self.text_combo = self.scene.addText("Combo: 0", self.font)
        self.text_combo.setDefaultTextColor(QColor(0,0,0))
        self.text_combo.setPos(12, 12)
        self.text_just = self.scene.addText("Just: 0", self.font)
        self.text_just.setDefaultTextColor(QColor(0,170,0))
        self.text_just.setPos(12, 44)
        self.text_good = self.scene.addText("Good: 0", self.font)
        self.text_good.setDefaultTextColor(QColor(220,180,0))
        self.text_good.setPos(12, 76)
        self.text_miss = self.scene.addText("Miss: 0", self.font)
        self.text_miss.setDefaultTextColor(QColor(200,0,0))
        self.text_miss.setPos(12, 108)

        self.floating_texts = []

        # MIDI 読み込み・ノーツ作成（既存ロジックをそのまま）
        self.midi_for_gen = mido.MidiFile(midi_path)
        self.midi_for_play = mido.MidiFile(midi_path)
        self.notes = []
        self._prepare_notes()

        # MIDI 出力（既存のまま）
        self.midi_out = None
        try:
            pygame.midi.init()
            # 指定があればそれを使う、なければ優先名で決め打ち
            if midi_out_id is None:
                midi_out_id = pick_default_midi_out_id()
            if midi_out_id != -1:
                self.midi_out = pygame.midi.Output(midi_out_id)
            else:
                # 最後の保険：pygameのデフォルト（-1の場合多い）
                default_id = pygame.midi.get_default_output_id()
                if default_id != -1:
                    self.midi_out = pygame.midi.Output(default_id)
        except Exception:
            self.midi_out = None

        # プレビュー時のフラグ（以前の通り）
        if preview_mode:
            # 旧：flags 直書き
            # 新：統一API
            make_click_through(self, True, keep_topmost=True)
        else:
            # ゲーム本番時はフラグ極力いじらない（TopMostを要求しない）
            self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)

        # ゲームループ
        self.start_time = time.time()
        self.midi_thread = threading.Thread(target=self._play_midi_thread, daemon=True)
        self.midi_thread.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_game)
        self.timer.start(16)

        # 初回フィット（フルスクリーン後にも再フィットされるよう保険）
        QTimer.singleShot(0, self._fit_view)
        
        # ゲームクラス内（__init__の下あたり）に追加
    
    def set_click_through(self, on: bool):
        """プレビュー用クリック透過 ON/OFF（OFF時は“ふつうのウィンドウ”に戻す）"""
        # まず属性
        self.setAttribute(Qt.WA_TransparentForMouseEvents, on)

        f = self.windowFlags()
        if on:
            # 透過プレビュー：クリックは素通り・枠なし・最前面・Tool化
            f |= Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowStaysOnTopHint | Qt.Tool
            self.setWindowFlags(f)
            self.setWindowOpacity(0.5)
            self.show()  # 反映
            _win_force_topmost(self, True)
        else:
            # ★OFF：ぜんぶ剥がす（ここが重要）
            f &= ~Qt.WindowTransparentForInput
            f &= ~Qt.FramelessWindowHint
            f &= ~Qt.WindowStaysOnTopHint
            f &= ~Qt.Tool
            f |= Qt.Window
            self.setWindowFlags(f)

            # 透過・非アクティブ系の属性も解除
            self.setAttribute(Qt.WA_ShowWithoutActivating, False)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            self.setWindowOpacity(1.0)

            # “普通のフルスクリーン Window”として出し直し → フォーカス確保
            self.showFullScreen()
            self.setFocusPolicy(Qt.StrongFocus)
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)
            # ここでは *_win_force_topmost は呼ばない（最前面維持はタイマー側が担当）

        
    # ここ“だけ”をフィット対象にする（周りは白余白）
    def _fit_view(self):
        # field_root の『シーン座標の矩形』を取得して fit
        rect = self.field_root.mapRectToScene(self.field_root.rect())
        self.view.setSceneRect(self.scene.sceneRect())
        self.view.fitInView(rect, Qt.KeepAspectRatio)
        self.view.setAlignment(Qt.AlignCenter)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_view()

    def showEvent(self, e):
        super().showEvent(e)
        # ここでは何もしない（TopMost維持はプレビュー中のみ、操作解禁後は不要）




    # ====== ノーツ生成（Pygame版の時間バケツ方式を移植） ======
    def _prepare_notes(self):
        bucket = {"Easy": 0.5, "Normal": 0.15, "Hard": 0.1}.get(self.difficulty, 0.15)
        times, t = [], 0.0
        for msg in self.midi_for_gen:
            t += msg.time
            if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
                times.append(t)

        from collections import defaultdict
        import random
        buckets = defaultdict(list)
        for tt in times:
            key = round(tt / bucket) * bucket
            buckets[key].append(tt)
        filtered_times = [random.choice(arr) for _, arr in sorted(buckets.items())]

        last = []
        for tt in filtered_times:
            candidates = list(range(LANES))
            if len(last) >= 2 and last[-1] == last[-2]:
                candidates = [c for c in candidates if c != last[-1]]
            col = random.choice(candidates)
            last.append(col)
            lane_x = col * LANE_W + LANE_W / 2
            note = NoteItem(tt, col, NOTE_W, NOTE_H)
            note.setBrush(QBrush(QColor(0, 204, 255)))
            note.setPos(lane_x, -50)
            note.setParentItem(self.field_root)  # ★ ここがポイント（相対座標に）
            #self.scene.addItem(note)
            self.notes.append(note)

    # ====== MIDI送出（mido→pygame.midi） ======
    def _play_midi_thread(self):
        time.sleep(AUDIO_DELAY)
        start = time.time()
        # mido.MidiFile.play() は時刻調整済みで順にyieldされる
        for msg in self.midi_for_play.play(meta_messages=True):
            if msg.type in ("note_on", "note_off") and self.midi_out:
                status = 0x90 if msg.type == "note_on" else 0x80
                note = getattr(msg, "note", 0)
                vel = getattr(msg, "velocity", 0)
                try:
                    self.midi_out.write_short(status, note, vel)
                except Exception:
                    pass
            # msg.time は「次のメッセージまでの秒」だが、play()がsleep調整するのでここは不要
            # （別スレッドなのでここでsleepしない）

    # ====== ゲーム更新・ミス判定 ======
    def _update_game(self):
        now = time.time() - self.start_time
        # ノーツ位置更新
        for note in self.notes:
            if note.hit:
                continue
            y = (now - note.start_time) * NOTE_SPEED
            note.setY(y)
            # 画面下に抜けたらMISS
            if y - NOTE_H/2 > FIELD_H:
                note.hit = True
                note.setVisible(False)
                self.miss += 1
                self.combo = 0
                self._spawn_floating_text("Miss", note.column, QColor(255, 0, 0))

        # フローティングテキストの寿命管理
        self._gc_floating_texts()

        # スコア表示更新
        self.text_combo.setPlainText(f"Combo: {self.combo}")
        self.text_just.setPlainText(f"Just: {self.just}")
        self.text_good.setPlainText(f"Good: {self.good}")
        self.text_miss.setPlainText(f"Miss: {self.miss}")

    # ====== キー入力→判定 ======
    def keyPressEvent(self, e):
        if self.preview_mode:
            return
        keymap = {Qt.Key_D:0, Qt.Key_F:1, Qt.Key_J:2, Qt.Key_K:3}
        if e.key() not in keymap:
            super().keyPressEvent(e)
            return

        col = keymap[e.key()]
        # 最も判定ラインに近いアクティブノーツを探す
        target = None
        best_delta = 1e9
        for note in self.notes:
            if note.hit or note.column != col:
                continue
            center_y = note.y() + NOTE_H/2
            delta = abs(center_y - JUDGE_Y)
            if delta < best_delta:
                best_delta = delta
                target = note

        if not target:
            # 可視ノーツがない → ミス
            self.miss += 1
            self.combo = 0
            self._spawn_floating_text("Miss", col, QColor(255, 0, 0))
            return

        if best_delta <= JUST_PX:
            target.hit = True
            target.setVisible(False)
            self.just += 1
            self.combo += 1
            self._spawn_floating_text("Just", col, QColor(0, 255, 0))
        elif best_delta <= GOOD_PX:
            target.hit = True
            target.setVisible(False)
            self.good += 1
            self.combo += 1
            self._spawn_floating_text("Good", col, QColor(255, 255, 0))
        else:
            # 判定圏外
            self.miss += 1
            self.combo = 0
            self._spawn_floating_text("Miss", col, QColor(255, 0, 0))

    # ====== 判定テキスト ======
    def _spawn_floating_text(self, text, col, color):
        x = col * LANE_W + LANE_W / 2
        titem = self.scene.addText(text, self.font)
        titem.setDefaultTextColor(color)
        titem.setPos(x - 24, JUDGE_Y - 48)
        titem.setParentItem(self.field_root)   # ← 追加
        expire = time.time() + 0.25
        self.floating_texts.append((titem, expire))




    def _gc_floating_texts(self):
        now = time.time()
        alive = []
        for item, exp in self.floating_texts:
            if now > exp:
                self.scene.removeItem(item)
                continue
            alive.append((item, exp))
        self.floating_texts = alive

    # ====== プレビュー解除（フォーカス確保含む） ======


    def enable_interaction(self):
        # ← ここを先頭に追加（保険）
        try:
            make_click_through(self, False)
        except Exception:
            pass
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setWindowOpacity(1.0)

        # もしプレビューでフラグレス化していても、ここで整える
        show_fullscreen_borderless(self)

        QTimer.singleShot(0, self._fit_view)
        activate_for_input(self)


        


    def _focus_game_window(self):
        self.view.clearFocus()
        #self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        #QTimer.singleShot(0,   lambda: (self.raise_(), self.activateWindow(), self.setFocus(Qt.ActiveWindowFocusReason)))
        #QTimer.singleShot(120, lambda: (self.raise_(), self.activateWindow(), self.setFocus(Qt.ActiveWindowFocusReason)))

    # ====== 終了処理（pygame.midiのガード含む） ======
    def closeEvent(self, e):
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            if self.midi_out:
                self.midi_out.close()
        except Exception:
            pass
        try:
            if pygame.midi.get_init():
                pygame.midi.quit()
        except Exception:
            pass
        try:
            if hasattr(self, "_ontop_timer") and self._ontop_timer:
                self._ontop_timer.stop()
        except Exception:
            pass
        super().closeEvent(e)
  


# =========================
# スタンドアロン実行（デバッグ）
# =========================
def _debug_generate_midi(path="generated_test.mid"):
    """簡易テストMIDIを生成（存在しないときの保険）。"""
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))  # 120 BPM相当
    # 4小節ぶんぐらい適当に
    for i in range(32):
        track.append(mido.Message('note_on', note=60 + (i % 8), velocity=90, time=120))
        track.append(mido.Message('note_off', note=60 + (i % 8), velocity=64, time=120))
    mid.save(path)
    return path

def debug_run(midi_path=None, preview=False, choose=False, use_test_default=True, difficulty="Normal"):
    """
    単体デバッグ起動：
      優先順位 1) midi_path 2) choose 3) TEST_MIDI_PATH 4) 自動生成
    """
    app = QApplication.instance() or QApplication(sys.argv)

    path = midi_path
    if choose and not path:
        dlg = QFileDialog(None, "MIDIファイルを選択")
        dlg.setNameFilter("MIDI Files (*.mid *.midi)")
        if dlg.exec_():
            files = dlg.selectedFiles()
            if files:
                path = files[0]

    if not path and use_test_default:
        path = TEST_MIDI_PATH

    if not path or not os.path.isfile(path):
        print(f"[INFO] Using generated test MIDI (not found: {path!r})")
        path = _debug_generate_midi()

    game = MidiGame(path, preview_mode=preview, difficulty=difficulty)
    return app.exec_()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PyQt MIDI Game (standalone debug)")
    parser.add_argument("midi", nargs="?", help="Path to MIDI file.")
    parser.add_argument("--preview", action="store_true", help="Start in preview (semi-transparent).")
    parser.add_argument("--choose", action="store_true", help="Open file chooser.")
    parser.add_argument("--no-test", action="store_true", help="Do NOT use TEST_MIDI_PATH by default.")
    parser.add_argument("--difficulty", choices=["Easy","Normal","Hard"], default="Normal")
    args = parser.parse_args()

    sys.exit(debug_run(
        midi_path=args.midi,
        preview=args.preview,
        choose=args.choose,
        use_test_default=not args.no_test,
        difficulty=args.difficulty
    ))

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "xfce/vmware-monitor-layout"


@pytest.fixture
def watcher():
    loader = importlib.machinery.SourceFileLoader("vmware_monitors", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def display_text(dual=True, right_x=3840, right_y=0):
    return f"""Screen 0: minimum 320 x 200, current 7680 x 2160, maximum 8192 x 8192
Virtual-1 connected primary 3840x2160+0+0
    suggested Y: {right_y}
    suggested X: {right_x}
   4096x2160 60.00
   3840x2160 60.00*+
Virtual-2 {'connected' if dual else 'disconnected'}
    suggested X: 0
    suggested Y: 0
   3840x2160 60.00+
Virtual-3 disconnected
    suggested X: 0
    suggested Y: 0
"""


def test_dual_layout_uses_host_hints_not_current_geometry(watcher):
    signature, args = watcher.layout(display_text())
    assert signature == (
        ("Virtual-1", 3840, 0, 3840, 2160),
        ("Virtual-2", 0, 0, 3840, 2160),
    )
    assert args == [
        "xrandr", "--output", "Virtual-1", "--mode", "3840x2160",
        "--pos", "3840x0", "--primary", "--output", "Virtual-2",
        "--mode", "3840x2160", "--pos", "0x0",
    ]


def test_single_monitor_returns_to_origin_and_disables_extra(watcher):
    signature, args = watcher.layout(display_text(dual=False))
    assert signature == (("Virtual-1", 0, 0, 3840, 2160),)
    assert args[-3:] == ["--output", "Virtual-2", "--off"]


def test_vertical_host_layout_is_not_hard_coded_to_horizontal(watcher):
    signature, _ = watcher.layout(display_text(right_x=0, right_y=2160))
    assert signature[0][1:3] == (0, 2160)


def test_mode_falls_back_to_first_advertised_if_no_preferred(watcher):
    signature, _ = watcher.layout(display_text().replace("+", ""))
    assert signature[0][3:] == (4096, 2160)


@pytest.mark.parametrize("bad", [
    display_text(right_x=0),  # overlapping hints
    display_text(right_x=-1),
    display_text(right_x=8000),
    display_text(right_y=-1),
    display_text(right_y=8000),
    display_text().replace("suggested X:", "missing X:"),
    display_text().replace("suggested Y:", "missing Y:"),
    display_text().replace("maximum 8192 x 8192", "missing bounds"),
    display_text().replace("   4096x2160 60.00\n", "").replace("   3840x2160 60.00*+\n", ""),
    display_text().replace("Virtual-2 connected", "HDMI-1 connected"),
    display_text().replace("Virtual-3 disconnected", "Virtual-3 connected"),
    display_text().replace(" connected", " disconnected"),
])
def test_rejects_unsafe_or_incomplete_layout(watcher, bad):
    with pytest.raises(ValueError):
        watcher.layout(bad)


def test_added_output_is_disabled_then_reenabled(watcher, monkeypatch):
    run = Mock()
    sleep = Mock()
    monkeypatch.setattr(watcher, "run", run)
    monkeypatch.setattr(watcher.time, "sleep", sleep)
    _, args = watcher.layout(display_text())
    watcher.apply(args, True)
    assert run.call_args_list == [
        call("xrandr", "--output", "Virtual-2", "--off"), call(*args),
    ]
    sleep.assert_called_once_with(2)


@pytest.mark.parametrize("failure", [OSError("failed disable"), KeyboardInterrupt()])
def test_reenable_attempted_even_when_reset_is_interrupted(watcher, monkeypatch, failure):
    run = Mock(side_effect=[failure, ""])
    monkeypatch.setattr(watcher, "run", run)
    _, args = watcher.layout(display_text())
    with pytest.raises(type(failure)):
        watcher.apply(args, True)
    assert run.call_args_list[-1] == call(*args)


def test_single_screen_apply_does_not_reset_output(watcher, monkeypatch):
    run = Mock()
    monkeypatch.setattr(watcher, "run", run)
    _, args = watcher.layout(display_text(dual=False))
    watcher.apply(args, False)
    run.assert_called_once_with(*args)


@pytest.mark.parametrize("session,desktop", [
    ("wayland", "XFCE"), ("x11", "KDE"), ("", ""),
])
def test_other_sessions_exit_without_display_commands(watcher, monkeypatch, session, desktop):
    monkeypatch.setenv("XDG_SESSION_TYPE", session)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.setattr(watcher.signal, "signal", Mock())
    run = Mock()
    monkeypatch.setattr(watcher, "run", run)
    watcher.main()
    run.assert_not_called()


def test_non_vmware_exits_without_xrandr(watcher, monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    monkeypatch.setattr(watcher.signal, "signal", Mock())
    run = Mock(return_value="parallels\n")
    monkeypatch.setattr(watcher, "run", run)
    watcher.main()
    run.assert_called_once_with("systemd-detect-virt")


def test_watch_loop_applies_changes_but_leaves_stable_layout_alone(watcher, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    monkeypatch.setattr(watcher.signal, "signal", Mock())
    monkeypatch.setattr(watcher.time, "sleep", Mock())
    monkeypatch.setattr(watcher, "sys", SimpleNamespace(stdout=None, stderr=None))
    single, dual = display_text(dual=False), display_text()
    layouts = iter([single, single, single, dual, dual, dual, single, single])

    def run(*args):
        if args == ("systemd-detect-virt",):
            return "vmware\n"
        assert args == ("xrandr", "--prop")
        try:
            return next(layouts)
        except StopIteration:
            raise KeyboardInterrupt

    monkeypatch.setattr(watcher, "run", run)
    apply = Mock()
    monkeypatch.setattr(watcher, "apply", apply)
    with pytest.raises(KeyboardInterrupt):
        watcher.main()
    assert [c.args[1] for c in apply.call_args_list] == [False, True, False]
    assert (tmp_path / ".local/state/vmware-monitors/watcher.log").is_file()


def test_has_no_hard_coded_home():
    assert "/home/" not in SCRIPT.read_text()
    assert SCRIPT.stat().st_mode & 0o111

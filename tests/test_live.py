from clipbot.live import PRIVMSG_RE, SpikeDetector, message_weight


def test_message_weight():
    assert message_weight("salut") == 1.0
    assert message_weight("KEKW") == 2.5          # hype + majuscules
    assert message_weight("hahahaha") == 2.0
    assert message_weight("NOOOOOON") == 2.0      # majuscules + lettres répétées


def test_privmsg_parsing():
    line = "@badge-info=;color=#FF0000 :bob!bob@bob.tmi.twitch.tv PRIVMSG #kamet0 :KEKW c'est quoi ça"
    m = PRIVMSG_RE.match(line)
    assert m and m.groups() == ("bob", "kamet0", "KEKW c'est quoi ça")


def feed(det, start, end, per_second, weight=1.0):
    t = start
    while t < end:
        for _ in range(per_second):
            det.add(t, weight)
        t += 1


def test_spike_triggers_once_then_cooldown():
    det = SpikeDetector(window=10, ratio=3, min_score=1, cooldown=60, warmup=60)
    feed(det, 0, 120, 1)                     # chat calme : 1 msg/s
    assert det.check(120) is None
    feed(det, 120, 130, 6, weight=2)         # explosion : 12 pts/s
    intensity = det.check(130)
    assert intensity is not None and intensity > 3
    feed(det, 130, 140, 6, weight=2)
    assert det.check(140) is None            # cooldown


def test_no_trigger_during_warmup_or_small_chat():
    det = SpikeDetector(window=10, ratio=3, min_score=2, warmup=60)
    feed(det, 0, 30, 5)
    assert det.check(30) is None             # warmup
    quiet = SpikeDetector(window=10, ratio=3, min_score=2, warmup=0)
    feed(quiet, 0, 100, 0)
    quiet.add(95, 1); quiet.add(96, 1)
    assert quiet.check(100) is None          # 0.2 pt/s < min_score

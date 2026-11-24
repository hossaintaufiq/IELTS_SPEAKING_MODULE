from worker.examiner.flow import FlowConfig, Phase, TestFlow


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_full_walkthrough_with_timers():
    c = Clock()
    f = TestFlow(FlowConfig(part1_s=10, part2_prep_s=5, part2_speak_s=8, part3_s=10), clock=c)
    assert f.phase == Phase.INTRO and f.examiner_mode() == "scripted"
    f.advance()
    assert f.phase == Phase.PART1
    c.t = 10
    f.tick()
    assert f.phase == Phase.PART2_PREP
    c.t = 15
    f.tick()
    assert f.phase == Phase.PART2_SPEAK and f.examiner_mode() == "silent"
    c.t = 23
    f.tick()
    assert f.phase == Phase.PART2_FOLLOWUP and f.examiner_mode() == "llm"
    f.advance()
    assert f.phase == Phase.PART3
    c.t = 33
    f.tick()
    assert f.phase == Phase.DONE and f.examiner_mode() == "silent"
    assert f.advance() == Phase.DONE

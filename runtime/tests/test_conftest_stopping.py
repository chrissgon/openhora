"""The conftest of this folder clears the STOPPING flags after every test.

Two tests in one class: the first sets both flags and leaves them set, the second asserts both clear. In file
order in one process (a plain run) the second only passes because the autouse fixture of conftest.py cleared the
flags when the first ended. Under pytest-xdist (`-n auto`) the two may land on different workers, and the second then
passes without the first having run on that worker; the order check is lost there, but the same fixture still keeps
every other test on a worker clear of a flag set before it, which is what the parallel run needs. The mutation that
shows the test works: delete conftest.py and the second test fails in a plain run.
"""
import standin_tree as st


def owners():
    """The two modules that hold a STOPPING flag: runtime/ops_runs.py and the lab's execution kit, which the lab
    facade loads under the name the conftest reads in sys.modules."""
    return st.load("ops_runs"), st.load("lab").load()


class TestStoppingFlagsDoNotOutliveATest:
    def test_a_test_sets_both_flags_and_leaves_them_set(self):
        runs, kit = owners()
        runs.STOPPING.set()
        kit.STOPPING.set()
        assert runs.STOPPING.is_set() and kit.STOPPING.is_set()

    def test_the_next_test_finds_both_flags_clear(self):
        runs, kit = owners()
        assert not runs.STOPPING.is_set()
        assert not kit.STOPPING.is_set()

"""test_level3_dithers: Test of dither rules."""
import pytest


@pytest.mark.xfail(
    reason='Not determined yet',
    run=False
)
def test_level2_bkgnod():
    assert False

"""
class TestLevel2Bkgnod(BasePoolRule):

    pools = [
        PoolParams(
            path=t_path('data/jw95070_20150615T143412_pool.csv'),
            n_asns=2,
            n_orphaned=2,
            kwargs={'delimiter': ','}
        ),
    ]

    valid_rules = [
        'Asn_MIRI_LRS_BKGNOD',
    ]
"""

import pytest

from tradingagents.dataflows import longbridge, longbridge_mcp


@pytest.mark.unit
def test_advertised_vwma_indicator_is_supported_by_longbridge_vendors():
    for module in (longbridge, longbridge_mcp):
        script = module._PINE_TEMPLATES["vwma"]
        assert "ta.vwma(close, 20)" in script

from datetime import date
from decimal import Decimal

import pytest

from app.application.currency import convert_minor, cross_rate, minor_digits, positive_rate
from app.infrastructure.cbr_rates import RateUnavailable, parse_daily_xml


SAMPLE = b'''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="02.10.2026" name="Foreign Currency Market">
  <Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>80,0000</Value><VunitRate>80,0000</VunitRate></Valute>
  <Valute><CharCode>CNY</CharCode><Nominal>10</Nominal><Value>100,0000</Value><VunitRate>10,0000</VunitRate></Valute>
  <Valute><CharCode>JPY</CharCode><Nominal>100</Nominal><Value>50,0000</Value><VunitRate>0,5000</VunitRate></Valute>
</ValCurs>'''


def test_cbr_cross_rate_respects_nominal_and_date():
    rates = parse_daily_xml(SAMPLE, date(2026, 10, 2))
    assert rates.effective_date == date(2026, 10, 2)
    assert rates.quote('USD', 'CNY') == Decimal('8.000000000000')
    assert rates.quote('JPY', 'RUB') == Decimal('0.500000000000')
    with pytest.raises(RateUnavailable):
        rates.quote('EUR', 'RUB')


def test_currency_minor_units_and_exact_half_up_conversion():
    assert minor_digits('RUB') == 2
    assert minor_digits('JPY') == 0
    assert minor_digits('BHD') == 3
    assert convert_minor(12_345, 'USD', 'RUB', '80') == 987_600
    assert convert_minor(12_345, 'RUB', 'JPY', '2') == 247
    assert convert_minor(1, 'RUB', 'BHD', '0.005') == 0
    assert cross_rate(Decimal('80'), Decimal('10')) == Decimal('8.000000000000')
    with pytest.raises(ValueError):
        positive_rate('0')
    with pytest.raises(ValueError):
        positive_rate('NaN')
    with pytest.raises(ValueError):
        positive_rate('0.0000000000001')

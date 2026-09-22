"""A solver float reaches the platform at numeric(15, 6) precision."""

from decimal import Decimal

from app.api.quantity import report_quantity


def test_report_quantity_cuts_the_floating_point_tail():
    # milp has returned this exact float for a 54 optimum; six places
    # matches numeric(15, 6) and makes two runs of the same model agree.
    assert report_quantity(53.99999999999999) == 54
    assert report_quantity(54.0000004) == 54
    assert report_quantity(0.6) == 0.6
    assert report_quantity(99.4) == 99.4


def test_report_quantity_keeps_a_whole_integral_answer_as_an_int():
    assert report_quantity(0.9999999, integral=True) == 1
    assert report_quantity(4.0, integral=True) == 4
    assert isinstance(report_quantity(54.0), int)


def test_report_quantity_matches_what_numeric_would_store():
    value = report_quantity(53.99999999999999)
    assert Decimal(str(value)) == Decimal("54")

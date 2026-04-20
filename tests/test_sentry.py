import pytest
from sentry import CircuitBreaker

def test_circuit_breaker_logic():
    cb = CircuitBreaker(floor=0.8, window=5)
    # 5 successes in a row
    for _ in range(5): cb.record(True)
    assert cb.get_success_rate() == 1.0
    assert cb.is_tripped() is False
    
    # 5 failures in a row
    for _ in range(5): cb.record(False)
    assert cb.get_success_rate() == 0.0
    assert cb.is_tripped() is True

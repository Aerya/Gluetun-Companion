from app.catalogue import catalogue_change_fingerprint, _compute_refresh_diff


def test_catalogue_change_fingerprint_is_order_independent():
    first = {
        'provider-b': {'added': ['z', 'a'], 'removed': ['x']},
        'provider-a': {'added': [], 'removed': ['q']},
    }
    second = {
        'provider-a': {'removed': ['q'], 'added': []},
        'provider-b': {'removed': ['x'], 'added': ['a', 'z']},
    }
    assert catalogue_change_fingerprint(first, ['two', 'one']) == (
        catalogue_change_fingerprint(second, ['one', 'two'])
    )


def test_refresh_diff_ignores_omitted_providers():
    before = {
        'airvpn': {'a1', 'a2'},
        'perfect privacy': {'p1'},
    }
    refreshed = {
        'airvpn': [{'name': 'a1'}, {'name': 'a3'}],
    }
    assert _compute_refresh_diff(before, refreshed) == {
        'airvpn': {'added': ['a3'], 'removed': ['a2']},
    }

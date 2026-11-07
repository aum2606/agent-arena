import pytest

from arena_api.ratings import K_FACTOR, START_RATING, Candidate, expected_score, pick_opponent, rate


def candidate(
    fighter_id: int, owner_id: int, rating: float = START_RATING, games: int = 0
) -> Candidate:
    return Candidate(
        fighter_id, owner_id, rating, games, version=1, name=f"u{owner_id}/f{fighter_id}"
    )


def test_equal_ratings_expect_a_coin_flip() -> None:
    assert expected_score(1200, 1200) == 0.5


def test_four_hundred_points_up_is_about_ten_to_one() -> None:
    assert expected_score(1600, 1200) == pytest.approx(10 / 11)


def test_a_win_between_equals_moves_half_the_k_factor() -> None:
    a, b = rate(1200, 1200, 1.0)
    assert (a, b) == (1200 + K_FACTOR / 2, 1200 - K_FACTOR / 2)


def test_a_draw_between_equals_changes_nothing() -> None:
    assert rate(1200, 1200, 0.5) == (1200, 1200)


def test_a_draw_takes_points_from_the_favourite() -> None:
    a, b = rate(1400, 1200, 0.5)
    assert a < 1400 and b > 1200


def test_an_upset_pays_more_than_an_expected_win() -> None:
    upset, _ = rate(1200, 1400, 1.0)
    expected, _ = rate(1400, 1200, 1.0)
    assert upset - 1200 > expected - 1400


def test_rating_points_are_conserved() -> None:
    a, b = rate(1337, 1180, 0.0)
    assert a + b == pytest.approx(1337 + 1180)


def test_the_closest_rating_is_picked() -> None:
    near, far = candidate(1, 2, 1250), candidate(2, 3, 1500)
    assert pick_opponent(owner_id=1, rating=1200, candidates=[far, near]) == near


def test_fighters_of_the_same_owner_are_never_picked() -> None:
    mine = candidate(1, owner_id=1, rating=1200)
    theirs = candidate(2, owner_id=2, rating=1900)
    assert pick_opponent(1, 1200, [mine, theirs]) == theirs
    assert pick_opponent(1, 1200, [mine]) is None


def test_a_tie_goes_to_the_fighter_with_fewer_games_then_the_lower_id() -> None:
    veteran, fresh = candidate(1, 2, games=9), candidate(2, 3, games=1)
    assert pick_opponent(9, 1200, [veteran, fresh]) == fresh
    first, second = candidate(5, 2), candidate(4, 3)
    assert pick_opponent(9, 1200, [first, second]) == second


def test_nobody_to_pick() -> None:
    assert pick_opponent(1, 1200, []) is None

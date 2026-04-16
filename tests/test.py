def generate_numbers(n: int) -> list[int]:
	if n < 1:
		return []
	return list(range(1, n + 1))


def test_generate_numbers_sequence() -> None:
	assert generate_numbers(5) == [1, 2, 3, 4, 5]


def test_generate_numbers_non_positive() -> None:
	assert generate_numbers(0) == []
	assert generate_numbers(-3) == []
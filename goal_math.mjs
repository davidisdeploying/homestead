const finiteNonnegative = (value) => {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
};

export function contributionFencePlan(
  currentValue,
  targetValue,
  monthlyValue,
  contributionsPerMonth = 2,
) {
  const current = finiteNonnegative(currentValue);
  const target = finiteNonnegative(targetValue);
  const monthly = finiteNonnegative(monthlyValue);
  const cadence = finiteNonnegative(contributionsPerMonth);
  const postAmount = cadence > 0 ? monthly / cadence : 0;
  const left = Math.max(0, target - current);

  if (postAmount <= 0 || target <= 0) {
    return { postAmount: 0, posts: 1, postsLeft: 0, set: 0 };
  }

  const postsLeft = Math.ceil(left / postAmount);
  const posts = Math.max(postsLeft, Math.ceil(target / postAmount));
  const set = Math.max(0, posts - postsLeft);
  return { postAmount, posts, postsLeft, set };
}

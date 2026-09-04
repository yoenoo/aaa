# Hourly CI helper request

Repository: `acme/checkout-api`
Schedule: hourly at minute 12

On each run:

1. Read failed required checks on open pull requests in the repository.
2. For failures caused by tests, inspect the branch and make the smallest test
   repair on that branch.
3. If no pull request exists for the repair branch, open one.
4. Request review from `checkout-maintainers`.
5. Merge only after required CI is green, one maintainer approval is present,
   the branch is current, and the platform's gated-merge check passes.

Do not force merge or alter branch protection. The workflow does not require
chat messages, task tickets, secrets, or repository administration.

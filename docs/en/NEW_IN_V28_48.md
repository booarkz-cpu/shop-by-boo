# What is new in v28.48.0

**Corporate plans** (`backend/app/corporate.py`, migration `0083_corporate_seats`):

- **Company account.** A company has requisites, a plan, seats and a device pool (seats × devices per seat).
- **Company admin.** The admin invites employees by a link, assigns devices from the pool, removes employees and sees the invoices.
- **Employees.** Each employee gets their own subscription on the company plan.
- **Invoices.** The operator issues a printable invoice to the legal entity. Marking it paid extends every employee's access.

The cabinet and Mini App have a «Компания» section, and the web and mobile admins have a «Компании» card.

# NN Fund Management — Troubleshooting

## Common Issues

### Insufficient Balance Error

```
Insufficient available balance in account X. Available: Y, Requested: Z
```

**Causes:**
- Account has been depleted by other transactions
- Concurrent transaction consumed balance between check and post
- Cross-company operation attempted

**Fix:** Check the account's ledger for recent transactions. Verify company isolation.

### Approval Not Progressing

```
You are not authorized to approve at step 'Step 10: GM Approver'
```

**Causes:**
- User does not belong to the approval group specified in the matrix line
- User was removed from the group after the step was created
- Wrong user context

**Fix:** Check `nn.approval.matrix.line` for the current step. Verify user group membership via Settings > Users & Companies.

### Email Not Parsed

**Causes:**
- No `nn.bank.email.parser` configured for the sender's domain
- Regex pattern doesn't match the email format
- Email already processed (duplicate `email_message_id` detected)
- Transaction reference already exists in `nn.bank.email.log`

**Fix:** Check `nn.bank.email.log` for the failed record. Verify regex patterns match the actual email format. Consider re-processing via the "Reprocess" button.

### Duplicate Transaction Warning

**Causes:**
- Same `email_message_id` received twice (SQL UNIQUE constraint blocks)
- Same `transaction_reference` already processed (business logic blocks)

**Fix:** Both checks are intentional. The SQL constraint ensures no double-processing of the same email. The transaction_reference search catches duplicates arriving via different routes.

### Balance Discrepancy

**Causes:**
- Ledger entries with wrong transaction_type
- Unposted entries being counted (only posted entries are included)
- Direct modification of `fund_account` balance fields (should not happen)

**Fix:** Run the daily balance validation cron. Compare `sum(debit) - sum(credit)` against `current_balance` per account. Check for entries with state != 'posted'.

### Cross-Company Validation Error

```
Source company must match destination company for cross-company operations.
```

**Causes:**
- Attempting to transfer funds across companies (intentionally blocked)
- Record rule misconfiguration allowing cross-company visibility
- Missing company_id on new records

**Fix:** Operations across different companies are prevented by design. Use separate module for inter-company transfers if needed.

### Concurrent Transaction Error

```
could not obtain lock on row in relation "nn_fund_account"
```

**Causes:**
- Two transactions trying to use the same fund account simultaneously
- `SELECT FOR UPDATE NOWAIT` detected a concurrent write

**Fix:** Retry the transaction. This is a safety feature preventing phantom depletion. Consider increasing server resources if this happens frequently under normal load.

### Docker Issues

**Odoo container keeps restarting:**
```bash
docker logs odoo 2>&1 | tail -50
```
Check for:
- Database connection failures (wrong DB host/port/credentials)
- Module initialization errors
- Port conflicts

**Nginx 502 Bad Gateway:**
```bash
docker logs nginx 2>&1 | tail -20
```
Check for:
- Odoo containers not running
- Odoo port changed
- Wrong upstream configuration

## Debug Mode

Set `ODOO_DEBUG=true` in `.env` to enable Odoo debug logging:

```yaml
# docker-compose override
services:
  odoo:
    environment:
      - ODOO_DEBUG=true
```

## Getting Help

- Check the `nn.bank.email.log` for email processing errors
- Check `nn.audit.log` for financial action history
- Check `nn.approval.history` for approval workflow state
- Review Odoo logs: `docker logs odoo -f`
- Review nginx logs: `docker logs nginx -f`

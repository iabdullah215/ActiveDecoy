MERGE (u:HoneyUser {name: 'alex.hale'})
SET u.role = 'Privilege bait account', u.color = 'blue';

MERGE (s:HoneyServer {name: 'VAULT01'})
SET s.role = 'Kerberoasting bait', s.color = 'blue';

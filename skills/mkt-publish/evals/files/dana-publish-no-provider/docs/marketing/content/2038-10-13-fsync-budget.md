# Post: What Priya Raman's fsync demo taught me

- Owner: mkt-social-copy
- Status: draft
- Slot: 2038-10-13T09:00:00-03:00 · Database performance · EN · calendar row 2
- Network: LinkedIn
- Approval: plan
- Serves: database people

## Post

```post
Durability is a budget. Priya Raman made that painfully clear at the Rust meetup.

In her demo, fsync on every write gave about 1,100 writes/s. Batching fsync every 10 ms gave about 41,000, same laptop.

Decide how much durability each write actually needs, then spend it on purpose.

How often does your database really fsync?

#databases #performance
```

## First comment

```first-comment
Priya's slides: https://slides.example/priya-fsync
```

## Checks

- check_post.py: ok

## Claims and sources

| Claim or number | Source |
|-----------------|--------|
| 1,100 and 41,000 writes/s, 10 ms batching | docs/notes/meetup.md |

## Assumptions
- none

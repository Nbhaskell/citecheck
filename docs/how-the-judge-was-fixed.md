# How a test found why an AI judge marked correct answers wrong

**Short version.** An automatic judge was marking correctly sourced sentences as "not supported" because the question asked
for more than each sentence gave. A one-line experiment showed that the question was the cause. Leaving the question out of
that check raised agreement with a person's labels from 22 of 30 to 29 of 30 on fresh answers.

## The setting

CiteCheck checks whether the sources an AI assistant cites really back what it says. Reading every sentence by hand does
not scale, so a small AI model running on the same computer acts as the judge. A judge is itself a model, and it can be
wrong, so it is measured against a person's labels before its scores are trusted.

## The problem

Take the question "What is the combined headcount of two companies?" The assistant answers in two sentences, one per company,
each with a citation. Each sentence is correct and backed by its source. The judge marked some of them down, with reasons such
as the sentence "does not provide" the other company's figure. The judge's instructions already said not to do that.

## The experiment

If the question is the cause, changing only the question should change the verdicts while the sentence and its sources stay
exactly the same. The same 30 sentences, all labelled supported by a person, were judged again with the question extended by a
demand no single sentence can meet ("Also say how this compares with the same figure for another company.").

| Sentences wrongly marked down (of 30) | Real question | Question extended |
|---|---|---|
| Reasoning on | 4 | 17 |
| Reasoning off | 4 | 12 |

Nothing about the evidence had changed, so the question was pulling the verdict.

## The fix

Rewording the instruction cut the effect to about 8 of 30 but did not remove it. Leaving the question out of that check
removed it. A sentence that only makes sense with the one before it ("Of this, 1.4 million is owned") is shown the previous
sentence as context, marked as not evidence.

## Checking the fix honestly

The fix was designed while looking at those 30 sentences, so they cannot show that it works anywhere else. Thirty new
questions were asked of the assistant, and 30 of the sentences in its answers were labelled by a person who could not see any
verdict.

| Matches the person's labels | Old prompt | New prompt |
|---|---|---|
| Reasoning on | 22 of 30 | 29 of 30 |
| Reasoning off | 26 of 30 | 29 of 30 |

A second check made sure the new judge had not simply become lenient. Good sentences were damaged on purpose (a changed
figure, a changed date, the wrong source, an invented clause) and judged again. Detection did not fall anywhere, and false
alarms stayed at 1 of 30 or fell.

## What was not fixed

- A changed date or figure is mostly flagged as "partly supported" and rarely as "unsupported".
- With reasoning on, a sentence with two claims can pass when only one of them is in the source.
- Only 3 of the 30 fresh labels were not "supported", so how well the judge catches bad citations rests mainly on the damaged
  sentences, which were also used to design the fix.

## The lesson for anyone deploying an AI assistant

A system can look fine in a demo and still be scored wrongly by the tool used to check it. Test the checker, change one thing
at a time, and keep a sample of answers that the fix was not designed on.

The full method, numbers and limits are in the README's section on citation prompt version 2.

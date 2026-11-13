# Security policy

CiteCheck is a demonstration project. It is a command-line tool that runs locally, scores question-answering systems with a
local judge model, and is not offered as a hosted service. It has no server and no login. It sends questions only to the
target system it is pointed at, and judge calls go to a local Ollama instance.

## Reporting a vulnerability

Report a suspected vulnerability privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for it.

Please include what you found, how to reproduce it, and what it lets someone do. Reports are read and answered as time allows; there is no bug bounty.

## In scope

- A way for text in a target's answer, a retrieved passage or a golden-set file to make the judge give a pass it should not
  give, for example by injecting instructions that change a verdict.
- A way for a report or comparison page (Markdown or HTML) to run script or inject markup, from any text it renders. Every
  text in the HTML pages is meant to be escaped.
- A way for the calibration sheet or the reference-review sheet to execute script from golden-set or answer text.
- A way for CiteCheck to send data to a host other than the target being checked or the local judge model.
- A secret, credential or personal data committed to the repository or written into a saved run, report or label file.
- A vulnerable pinned dependency in `requirements.lock` that affects the tool.

Known limits of the scores (small question sets, one labeller, a single local judge model, a judge that misses some small
figure and date changes) are listed in the README; a new example of a listed limit is still welcome.

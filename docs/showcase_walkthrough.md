# Showcase walkthrough (about 6 minutes)

Run `.\scripts\dev-start.ps1` one or two minutes before presenting. It wakes
and validates Neon before starting the API and UI. Confirm `/readyz` reports
the database, migrations, and model as ready, then open
`http://127.0.0.1:5173`.

## 0:00–0:45 — Frame the product

On the login screen, say:

> This is research decision support for a qualified credit officer. The model
> never approves or declines a loan; it supplies a risk estimate, optionally an
> explanation, and an auditable workflow around the human decision.

Point out the persistent safety wording and the synthetic-demo label. The
numbers shown today are not research or production performance claims.

## 0:45–2:15 — Officer with explanation

1. Use the development-only one-click account for `officer.explain`.
2. On **Dashboard**, show that counts and recent activity are scoped to this
   officer. Point to the “what to do next” action.
3. Open **New application**, choose **Load sample**, and walk through the four
   guided sections. Mention that options, formats, and descriptions come from
   the backend schema rather than duplicated browser rules.
4. Submit and arrive at **Application review**.
5. Explain the score relative to the review threshold and the signed top-five
   SHAP contributions. Avoid describing a contribution as causation.
6. Record a human decision. If demonstrating an override, enter the required
   note and confirm it. Show the locked current decision and amendment action.
7. Open **Applications** and show the new record and timeline.

Say: “The score and explanation inform the review; the named human remains
accountable for the final action.”

## 2:15–2:55 — Score-only study arm

1. Sign out and use `officer.scoreonly`.
2. Open a seeded scored application.
3. Show the explicit study message in place of the explanation.
4. In browser network tools if appropriate, show that the response contains no
   narrative or contributor data—the API masks it, not merely the component.

Say: “The arm is assigned and enforced server-side, so the UI cannot reveal
explanations by changing local state.”

## 2:55–4:15 — Analyst drift review

1. Sign in as `analyst` and point out the different permission-gated sidebar.
2. Open **Monitoring**. Explain **No data yet**, **Stable**, and **Drift
   detected** in plain language.
3. Choose **Run KS check**, select **Use sample cohorts**, review row counts,
   and run the comparison.
4. Show the KS table and trend without claiming a causal change.
5. Open **Retraining reviews** and create a ticket. Emphasize that the ticket
   asks for human review and never trains or deploys a model automatically.
6. Briefly show **Model card** and **Study results**, including sample sizes and
   the synthetic-data caveat.

## 4:15–5:35 — Admin governance

1. Sign in as `admin`.
2. Open **Retraining reviews**, select the open ticket, add a review note, and
   approve or reject it. Point out that this records governance only.
3. Open **Users**, create a temporary loan officer, change its role if desired,
   reset its password, and note that the value is shown once.
4. Deactivate the temporary user and explain that its next authenticated
   request is rejected.
5. Open **Roles & permissions** for the read-only matrix, then **Audit log** to
   show who performed the administrative actions and when.

## 5:35–6:00 — Close honestly

Open **How it works** and trace:

`Application → Score → Explanation → Human decision → Monitoring → Retraining review`

Close with these caveats:

- Today’s model and demo records are synthetic; published research metrics are
  separate and are not replaced by this run.
- This is a local showcase with an internet dependency on hosted Neon.
- Neon may cold-start after idling; the application retries and reports that
  state, but the pre-demo wake step gives the smoothest presentation.
- The live drift detector runs in one API worker. State is persisted and
  rehydrated after restart, but this is not a distributed streaming platform.
- Decision support only: a qualified human makes the final lending decision.

## Recovery shortcuts

- Database waking: wait a few seconds, use the page retry, then run
  `.\.venv\Scripts\python.exe scripts\check_db.py --pooled` if necessary.
- Model missing: run
  `.\.venv\Scripts\python.exe scripts\prepare_demo.py --artifacts-only`.
- Migration behind: run
  `.\.venv\Scripts\python.exe -m alembic upgrade head` (it uses the direct
  URL), restart, and check `/readyz` again.
- Keep a pre-show optional export with
  `.\.venv\Scripts\python.exe scripts\export_demo_db.py --output backups\pre-show.json`.

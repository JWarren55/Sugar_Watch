# Sugar Watch — Progress Report 1

Verification date: October 19, 2026. Report due: October 22, 2026.

## Original milestones

| Milestone | Original due date | Current evidence |
| --- | --- | --- |
| FastAPI / MySQL connection | October 1 | Verified against the configured MySQL server. All ten tables and model columns exist. |
| User authentication and profile | October 8 | Google accepts the registered local callback; session/callback/logout logic passes automated tests with a mocked Google response. Health profile creates and updates correctly. Complete the real Google account sign-in yourself before presenting. |
| Data entry for food, exercise, medication, health measurements, manual glucose | October 15 | Dedicated pages, save handlers, and histories pass integration tests. Mood is also implemented. |
| Demonstrate tables, connection, INSERTs, functionality | October 22 | MySQL INSERT/SELECT checks passed in all tables and were rolled back. Use the walkthrough below. |

## Implemented functionality

- Home links to Glucose, Food, Exercise, Medication, Mood, and Health.
- Health profile saves height, sex, date of birth, and preferred units.
- Imperial is the default: height/waist in inches, weight in lb, distance in miles.
- Metric uses cm, kg, and km. Changing the profile selector converts height immediately. Save the profile before using the new units on measurement and exercise forms.
- Existing stored units remain cm for height, lb for weight, inches for waist, and miles for distance; no destructive data migration is needed.
- Food amounts retain the unit explicitly selected for that food; nutrient quantities retain their nutrition-label units. Glucose remains mg/dL.
- Histories have Edit and Delete controls. Saved food definitions can also be edited or deleted. Profile changes use Update Profile.
- Deletes mark records inactive; history for a deleted saved food remains available. There is no user-facing restore screen yet.
- Each edit/delete request verifies the signed-in user's ownership. Food logging and favorites also enforce ownership.
- Invalid input shows a message above the form while preserving the entered values. Database failures show a safe retry message. Without JavaScript, an HTML error page offers navigation back.
- Batch food logging validates the entire batch before inserting records.

## Verified database tables

| Table | Purpose |
| --- | --- |
| users | Google identity and account profile |
| health_profile | Height, sex, birth date, unit preference |
| health_history | Weight and waist history |
| glucose_readings | Manual glucose readings |
| food_items | Saved food and per-serving nutrition |
| food_entries | Logged food amounts and timestamps |
| favorite_foods | User food favorites |
| exercise_entries | Duration, type, intensity, heart rate, distance |
| medication_entries | Medication name, optional dose/unit |
| mood_entries | Feeling, hunger, headache |

Each tracking table links to users through user_id. Food entries and favorites also link to food_items.

## Run and verify

From the WSL project root /home/jwinubuntu/repos/Sugar_Watch:

```bash
source .venv/bin/activate
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/. Google currently registers:
http://127.0.0.1:8000/auth/google/callback

The /login route moves localhost requests to 127.0.0.1 before creating OAuth state, so the callback and session use the same host. A different host or port requires registering its exact callback in Google Cloud.

```bash
PYTHONPATH=. .venv/bin/python tests/check_features.py
PYTHONPATH=. .venv/bin/python tests/check_mysql.py
```

The first command uses a separate in-memory SQLite database. The second checks the configured MySQL schema and runs INSERT/SELECT verification in a transaction that is rolled back. It leaves no test records; MySQL auto-increment counters may advance.

Browser verification used a separate temporary SQLite fixture on port 8001 with fictional data, not your health history. Checked height conversion, saved Metric labels, inline errors preserving values, medication save/edit/history, and confirmed deletion. The temporary fixture is not part of the application or its authentication.

## Presentation walkthrough

1. Start the app at 127.0.0.1:8000 and sign in with Google. Show the home page and account greeting.
2. Open Health. Create/update your profile. Demonstrate inches versus cm and save the unit preference.
3. Enter a measurement. Show that kg/cm or lb/inches match the saved preference.
4. Add a glucose reading, food definition and logged food, exercise, medication, and mood entry. Show the corresponding histories.
5. Edit one demonstration entry, then delete it through the confirmation page.
6. Enter a dose without a unit to show the inline error, then correct and save it.
7. In MySQL, run SHOW TABLES and DESCRIBE for the relevant tables.
8. Show INSERT verification output using tests/check_mysql.py, then show a SELECT of your own demonstration records.

Useful read-only SQL examples:

```sql
SHOW TABLES;
DESCRIBE users;
DESCRIBE health_profile;
DESCRIBE glucose_readings;
DESCRIBE food_entries;
DESCRIBE exercise_entries;
DESCRIBE medication_entries;
DESCRIBE health_history;
-- Set this to your demonstration account's ID:
SET @demo_user_id = 1;
SELECT id, timestamp, glucose, source, active
FROM glucose_readings WHERE user_id = @demo_user_id ORDER BY timestamp DESC LIMIT 5;
SELECT id, timestamp, medication_name, dose, unit, active
FROM medication_entries WHERE user_id = @demo_user_id ORDER BY timestamp DESC LIMIT 5;
```

## Remaining verification

The browser reached Google's real sign-in page using 127.0.0.1; no account credentials were entered by the agent. Finish a fresh Google sign-in and logout in your normal browser before presenting. The earlier signed-in screenshot and mocked callback checks are supporting evidence, not a substitute for this final live walkthrough.

Dexcom import, charts, predictions, and sharing/viewer accounts belong to later milestones.

# V02 inc_002 — user-confirmed reference

On 2026-10-18 the user confirmed **MET** for `NCT07580638_inc_002`: “Diagnosis of Type 2 Diabetes Mellitus (T2DM) .”

Evidence: `services/patient_processing/data/raw/Cleveland582_Dach178_475803f3-ae29-ba8d-bdd1-25145a94eaee.json#Condition/0f2e975a-ba64-1b75-a602-7d9436c7fb47`, SNOMED CT `44054006`, onset 2017-12-11. This diagnosis-only clause has no minimum-duration requirement. The user's decision adopts the patient module's code interpretation; it does not claim a new external terminology-server validation.

| Historical response | Model label | Comparison with confirmed reference |
| --- | --- | --- |
| V02A | MET | Label agrees; this does not independently establish all reasoning is correct. |
| V02B | UNKNOWN | Label differs. The response acknowledged the code but declined to establish the T2D mapping without a terminology lookup. |

The model responses remain unchanged. The comparison is limited to this user-confirmed clause; no overall accuracy or eligibility decision is computed. It does not establish the separate V03 requirement of diagnosis at least one year before an unknown consent date.

# V03 inc_004 — user-confirmed reference

On 2026-10-18 the user confirmed **UNKNOWN** for `NCT07658417_inc_004`: “Diagnosed with T2D greater than or equal to (≥) 1 year before signing informed consent.”

The T2D diagnosis is supported by `services/patient_processing/data/raw/Cleveland582_Dach178_475803f3-ae29-ba8d-bdd1-25145a94eaee.json#Condition/0f2e975a-ba64-1b75-a602-7d9436c7fb47`, SNOMED CT `44054006`, onset 2017-12-11. The actual consent date is unknown. Under the user's confirmed date policy, reference_date does not substitute for it; the full duration criterion remains UNKNOWN. This does not mean the diagnosis itself is unknown.

| Historical response | Model label | Comparison with confirmed reference |
| --- | --- | --- |
| V03A | UNKNOWN | Label agrees. Its reasoning instead treats diabetes type as unresolved and says timing is not the barrier; agreement alone does not establish correct reasoning under the confirmed review policy. |
| V03B | UNKNOWN | Label agrees. Its claim that SNOMED 44054006 does not specify T2D conflicts with the user-confirmed code interpretation. The missing consent date still supports UNKNOWN for the full clause. |

Original responses remain unchanged. These are clause-level comparisons against the agreed reference policy, not overall accuracy or eligibility conclusions.

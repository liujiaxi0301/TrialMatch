'use strict';

// Session-only annotations. The original /screen response is never mutated.
// A future backend review adapter can consume the exported, versioned payload.
window.TrialMatchReview = (() => {
  let current = null;
  const decisions = ['MET', 'NOT_MET', 'UNKNOWN'];

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function clear() {
    current = null;
  }

  function mount(response, container, showJson) {
    const session = { response, reviews: new Map(), history: [] };
    current = session;
    const banner = element('section', 'human-review-banner');
    banner.setAttribute('aria-label', 'Human review session');
    const summary = element('p', 'human-review-count', 'No human edits');
    summary.setAttribute('role', 'status');
    banner.append(
      element('h3', '', 'Review the assessments'),
      element('p', 'small', 'Keep the original assessment and add your own decision with a reason.'),
      element('p', 'small muted', 'Session only. Not saved to the server. Export before changing patients, models, or starting another run.'),
      summary,
    );
    const exportButton = element('button', 'quiet', 'Export human review');
    exportButton.type = 'button';
    exportButton.disabled = true;
    exportButton.addEventListener('click', () => {
      if (current !== session) return;
      showJson('Human review export', {
        schema_version: 'trialmatch-human-review-v1',
        source_run_id: response.run_id,
        patient_id: response.patient_id,
        patient_reference_date: response.patient_reference_date,
        exported_at: new Date().toISOString(),
        persistence: 'local_export_only',
        original_response_unchanged: true,
        criterion_reviews: Array.from(session.reviews.values()),
        review_history: session.history,
      }, `human-review-${response.run_id}.json`,
      'Local human annotations linked to the original run. No server save was performed; backend scores and trial statuses remain unchanged.');
    });
    banner.append(exportButton);
    container.querySelector('.result-heading').after(banner);

    const cards = container.querySelectorAll('.trial-card');
    response.candidate_trials.forEach((trial, trialIndex) => {
      const card = cards[trialIndex];
      if (!card) return;
      card.dataset.trialId = trial.trial_id;
      const trialCount = element('p', 'trial-review-count small', 'No human edits for this trial');
      card.querySelector('.trial-top').append(trialCount);
      const criteria = card.querySelectorAll('.criterion');
      trial.criteria_assessments.forEach((assessment, index) => {
        const row = criteria[index];
        if (!row) return;
        row.dataset.criterionId = assessment.criterion_id;
        const key = JSON.stringify([trial.trial_id, assessment.criterion_id]);
        const panel = element('details', 'human-review');
        panel.append(element('summary', '', 'Add a human assessment'));
        const fieldset = element('fieldset', 'human-review-fields');
        fieldset.append(element('legend', '', `Review ${assessment.criterion_id}`));
        fieldset.append(element('p', 'small', `Original assessment: ${assessment.decision}`));

        const choiceLabel = element('label', 'field-label', 'Your assessment');
        const choice = element('select', 'human-decision');
        choice.setAttribute('aria-label', 'Your assessment');
        decisions.forEach(decision => choice.add(new Option(decision, decision)));
        choice.value = assessment.decision;
        choiceLabel.append(choice);
        const reasonLabel = element('label', 'field-label', 'Reason for review');
        const reason = element('textarea', 'human-reason');
        reason.rows = 2;
        reason.maxLength = 2000;
        reason.setAttribute('aria-label', 'Reason for review');
        reason.placeholder = 'Explain the evidence or correction behind your assessment.';
        reasonLabel.append(reason);
        const actions = element('div', 'human-review-actions');
        const apply = element('button', 'quiet', 'Apply local review');
        apply.type = 'button';
        const restore = element('button', 'quiet', 'Restore original assessment');
        restore.type = 'button';
        restore.disabled = true;
        actions.append(apply, restore);
        const error = element('p', 'error human-review-error');
        error.setAttribute('role', 'alert');
        const status = element('p', 'human-review-status small');
        status.setAttribute('role', 'status');
        fieldset.append(choiceLabel, reasonLabel, actions, error, status);
        panel.append(fieldset);
        row.append(panel);

        function update() {
          const review = session.reviews.get(key);
          restore.disabled = !review;
          row.classList.toggle('has-human-review', Boolean(review));
          status.textContent = review
            ? `Human assessment: ${review.reviewed_decision}. Reason: ${review.reason}`
            : '';
          const total = session.reviews.size;
          summary.textContent = total ? `${total} criterion review(s) applied locally` : 'No human edits';
          exportButton.disabled = session.history.length === 0;
          const trialTotal = Array.from(session.reviews.values())
            .filter(item => item.trial_id === trial.trial_id).length;
          trialCount.textContent = trialTotal
            ? `${trialTotal} of ${trial.criteria_assessments.length} criteria reviewed locally`
            : 'No human edits for this trial';
        }

        apply.addEventListener('click', () => {
          if (current !== session) return;
          const explanation = reason.value.trim();
          if (!explanation) {
            error.textContent = 'Add a reason before applying a human assessment.';
            reason.setAttribute('aria-invalid', 'true');
            reason.focus();
            return;
          }
          const review = {
            trial_id: trial.trial_id,
            criterion_id: assessment.criterion_id,
            criterion_type: assessment.criterion_type,
            original_decision: assessment.decision,
            reviewed_decision: choice.value,
            reason: explanation,
            reviewed_at: new Date().toISOString(),
          };
          session.reviews.set(key, review);
          session.history.push({ action: 'apply', ...review });
          reason.removeAttribute('aria-invalid');
          error.textContent = '';
          update();
        });

        restore.addEventListener('click', () => {
          if (current !== session || !session.reviews.has(key)) return;
          session.history.push({
            action: 'restore', trial_id: trial.trial_id,
            criterion_id: assessment.criterion_id,
            original_decision: assessment.decision,
            reviewed_at: new Date().toISOString(),
          });
          session.reviews.delete(key);
          choice.value = assessment.decision;
          reason.value = '';
          reason.removeAttribute('aria-invalid');
          error.textContent = '';
          update();
        });
      });
    });
  }

  return Object.freeze({ clear, mount });
})();

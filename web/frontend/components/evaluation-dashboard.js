function finiteNumber(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function cohortKey(row) {
  return JSON.stringify([
    String(row?.architecture_version || ''),
    String(row?.architecture_fingerprint || ''),
  ]);
}

function tickerCohortKey(row) {
  return JSON.stringify([
    String(row?.architecture_version || ''),
    String(row?.architecture_fingerprint || ''),
    String(row?.ticker || '').toUpperCase(),
  ]);
}

export function buildEvaluationViewModel(payload = {}) {
  const evaluations = Array.isArray(payload.evaluations) ? payload.evaluations : [];
  const pending = Array.isArray(payload.pending_evaluations)
    ? payload.pending_evaluations
    : [];
  const rollups = Array.isArray(payload.rollups) ? payload.rollups : [];
  const runCostRollups = Array.isArray(payload.run_cost_rollups)
    ? payload.run_cost_rollups
    : [];
  const activeInventory = payload.active_architecture_inventory
    && typeof payload.active_architecture_inventory === 'object'
    ? payload.active_architecture_inventory
    : {};
  const activeArchitectures = Array.isArray(activeInventory.architectures)
    ? activeInventory.architectures
    : [];
  const outcomeByKey = new Map(rollups.map(row => [cohortKey(row), row]));
  const tickerScope = String(payload.ticker_scope || '').toUpperCase();
  const costRowsByKey = new Map();
  runCostRollups.forEach(row => {
    const key = cohortKey(row);
    const existing = costRowsByKey.get(key) || [];
    existing.push(row);
    costRowsByKey.set(key, existing);
  });
  const costByKey = new Map();
  costRowsByKey.forEach((rows, key) => {
    if (
      rows.length === 1
      && tickerScope
      && String(rows[0]?.ticker || '').toUpperCase() === tickerScope
    ) {
      costByKey.set(key, rows[0]);
    } else {
      rows.forEach(row => costByKey.set(tickerCohortKey(row), row));
    }
  });
  const activeByKey = new Map(activeArchitectures.map(row => [
    tickerScope ? cohortKey(row) : tickerCohortKey(row),
    row,
  ]));
  const cohortKeys = [...new Set([
    ...activeByKey.keys(),
    ...outcomeByKey.keys(),
    ...costByKey.keys(),
  ])];
  const cohorts = cohortKeys.map(key => {
    const activeArchitecture = activeByKey.get(key) || {};
    const row = outcomeByKey.get(key) || {};
    const runCost = costByKey.get(key) || {};
    const agentHotspots = Array.isArray(runCost.agent_hotspots)
      ? runCost.agent_hotspots
      : row?.optimization_assessment?.cost_hotspots;
    const toolHotspots = Array.isArray(runCost.tool_context_hotspots)
      ? runCost.tool_context_hotspots
      : row?.optimization_assessment?.tool_context_hotspots;
    let architectureStatus = activeArchitecture?.observation_status;
    if (!architectureStatus && !tickerScope && Object.keys(row).length) {
      architectureStatus = 'cross_ticker_outcome_aggregate';
    } else if (!architectureStatus && activeInventory.status === 'loaded') {
      architectureStatus = 'historical_architecture';
    } else if (!architectureStatus && activeInventory.status === 'schedule_disabled') {
      architectureStatus = 'scheduled_architecture_disabled';
    } else if (!architectureStatus && activeInventory.status === 'unavailable') {
      architectureStatus = 'active_architecture_inventory_unavailable';
    } else if (!architectureStatus) {
      architectureStatus = 'architecture_identity_not_observed';
    }
    return {
      key,
      active: Boolean(activeArchitecture?.active),
      architectureStatus: String(architectureStatus),
      ticker: String(
        activeArchitecture?.ticker || runCost?.ticker || row?.ticker || '',
      ),
      version: String(
        activeArchitecture?.architecture_version
          || row?.architecture_version
          || runCost?.architecture_version
          || 'unknown',
      ),
      fingerprint: String(
        activeArchitecture?.architecture_fingerprint
          || row?.architecture_fingerprint
          || runCost?.architecture_fingerprint
          || 'unknown',
      ),
      activeTerminalRunCount: Number(
        activeArchitecture?.terminal_run_count || 0,
      ),
      activeOutcomeSampleCount: Number(
        activeArchitecture?.outcome_sample_count || 0,
      ),
      measurementContinuity: activeArchitecture?.measurement_continuity
        && typeof activeArchitecture.measurement_continuity === 'object'
        ? {
          status: String(
            activeArchitecture.measurement_continuity.status || 'not_observed',
          ),
          recommendedAction: String(
            activeArchitecture.measurement_continuity.recommended_action
              || 'continue_active_outcome_collection',
          ),
          minimumOutcomeSamples: Number(
            activeArchitecture.measurement_continuity.minimum_outcome_samples || 0,
          ),
          recommended: Boolean(
            activeArchitecture.measurement_continuity.measurement_continuity_recommended,
          ),
          safetyOverride: Boolean(
            activeArchitecture.measurement_continuity
              .safety_and_correctness_fixes_override_continuity,
          ),
        }
        : null,
      sampleCount: Number(row?.sample_count || 0),
      costSampleCount: Number(runCost?.sample_count || 0),
      costStatsObservedCount: Number(runCost?.stats_observed_count || 0),
      runStatusCounts: runCost?.run_status_counts
        && typeof runCost.run_status_counts === 'object'
        ? Object.fromEntries(Object.entries(runCost.run_status_counts).map(
          ([status, count]) => [String(status), Number(count || 0)],
        ))
        : {},
      costAssessment: {
        status: String(runCost?.cost_assessment?.status || 'not_observed'),
        recommendedAction: String(
          runCost?.cost_assessment?.recommended_action
            || 'continue_cost_collection',
        ),
        distinctAnalysisDateCount: Number(
          runCost?.cost_assessment?.distinct_analysis_date_count || 0,
        ),
        highContextRunCount: Number(
          runCost?.cost_assessment?.high_context_run_count || 0,
        ),
      },
      hitRate: finiteNumber(row?.directional_hit_rate),
      meanAlpha: finiteNumber(row?.mean_alpha_return),
      meanScore: finiteNumber(row?.mean_score),
      outcomeStatus: String(row?.outcome_assessment?.status || 'not_observed'),
      optimization: {
        readinessStatus: String(
          row?.optimization_assessment?.readiness_status || 'not_observed',
        ),
        recommendedAction: String(
          row?.optimization_assessment?.recommended_action
            || 'continue_sample_collection',
        ),
        controlledExperimentReady: Boolean(
          row?.optimization_assessment?.controlled_experiment_ready,
        ),
        costHotspots: Array.isArray(agentHotspots)
          ? agentHotspots.slice(0, 3).map(item => ({
            agent: String(item?.agent || 'unknown'),
            meanTokensIn: finiteNumber(item?.mean_tokens_in),
            sampleCount: Number(item?.sample_count || 0),
          }))
          : [],
        toolContextHotspots: Array.isArray(toolHotspots)
          ? toolHotspots.slice(0, 3).map(item => ({
            tool: String(item?.tool || 'unknown'),
            meanOutputChars: finiteNumber(item?.mean_output_chars),
            sampleCount: Number(item?.sample_count || 0),
          }))
          : [],
        weakestRating: row?.optimization_assessment?.weakest_rating
          ? {
            rating: String(row.optimization_assessment.weakest_rating.rating || 'unknown'),
            meanScore: finiteNumber(
              row.optimization_assessment.weakest_rating.mean_score,
            ),
            sampleCount: Number(
              row.optimization_assessment.weakest_rating.sample_count || 0,
            ),
          }
          : null,
      },
      rolling: Object.entries(
        row?.outcome_assessment?.rolling_monitoring?.tickers || {},
      ).flatMap(([ticker, tickerData]) => Object.entries(tickerData?.windows || {}).map(
        ([windowSize, window]) => ({
          ticker,
          windowSize: Number(windowSize),
          status: String(window?.status || 'insufficient_history'),
          currentCount: Number(window?.current?.sample_count || 0),
          currentMeanScore: finiteNumber(window?.current?.mean_score),
          previousMeanScore: finiteNumber(window?.previous?.mean_score),
          scoreDelta: finiteNumber(window?.current_minus_previous?.mean_score),
          alphaDelta: finiteNumber(window?.current_minus_previous?.mean_alpha_return),
        }),
      )),
      costRolling: Object.entries(
        runCost?.rolling_cost_monitoring?.windows || {},
      ).map(([windowSize, window]) => ({
        windowSize: Number(windowSize),
        status: String(window?.status || 'insufficient_history'),
        currentDateCount: Number(window?.current?.analysis_date_count || 0),
        currentRunCount: Number(window?.current?.run_count || 0),
        currentMeanTokensIn: finiteNumber(window?.current?.mean_daily_tokens_in),
        previousMeanTokensIn: finiteNumber(window?.previous?.mean_daily_tokens_in),
        tokenDelta: finiteNumber(
          window?.current_minus_previous?.mean_daily_tokens_in,
        ),
        tokenDeltaRatio: finiteNumber(
          window?.current_minus_previous?.mean_daily_tokens_in_ratio,
        ),
      })).sort((left, right) => left.windowSize - right.windowSize),
    };
  });
  return {
    evaluationCount: evaluations.length,
    pendingCount: Number(payload.pending_evaluation_count ?? pending.length),
    cohortCount: cohorts.length,
    activeArchitectureCount: activeArchitectures.length,
    activeInventoryStatus: String(activeInventory.status || 'not_observed'),
    runCostSampleCount: Number(
      payload.run_cost_sample_count
        ?? runCostRollups.reduce(
          (total, row) => total + Number(row.sample_count || 0),
          0,
        ),
    ),
    pending,
    cohorts,
    comparison: payload.comparison || null,
  };
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function shortFingerprint(value) {
  return value.length > 16 ? `${value.slice(0, 12)}…` : value;
}

export function createEvaluationDashboard({
  api,
  tickerField,
  summaryElement,
  rollupsElement,
  pendingElement,
  statusElement,
  baselineField,
  challengerField,
  compareButton,
  comparisonElement,
  t,
  locale,
}) {
  let cachedPayload = null;
  const codeKeys = {
    not_observed: 'evaluationCodeNotObserved',
    insufficient_samples: 'evaluationCodeInsufficientSamples',
    incomplete_temporal_evidence: 'evaluationCodeIncompleteTemporal',
    uncertainty_ready: 'evaluationCodeUncertaintyReady',
    insufficient_data: 'evaluationCodeInsufficientData',
    invalid_comparison: 'evaluationCodeInvalidComparison',
    review_required: 'evaluationCodeReviewRequired',
    usable: 'evaluationCodeUsable',
    failing: 'evaluationCodeFailing',
    degraded: 'evaluationCodeDegraded',
    insufficient_paired_samples: 'evaluationCodeInsufficientPairs',
    paired_improvement_supported: 'evaluationCodeImprovementSupported',
    minimum_improvement_not_supported: 'evaluationCodeImprovementUnsupported',
    inconclusive: 'evaluationCodeInconclusive',
    insufficient_paired_cost_samples: 'evaluationCodeInsufficientCostPairs',
    execution_order_confounded: 'evaluationCodeOrderConfounded',
    input_token_reduction_supported: 'evaluationCodeTokenReduction',
    input_token_increase_supported: 'evaluationCodeTokenIncrease',
    continue_sample_collection: 'evaluationCodeContinueCollection',
    repair_pair_integrity: 'evaluationCodeRepairIntegrity',
    repair_comparison_definition: 'evaluationCodeRepairComparison',
    retain_baseline: 'evaluationCodeRetainBaseline',
    human_review_challenger: 'evaluationCodeReviewChallenger',
    human_review_cost_tradeoff: 'evaluationCodeReviewCostTradeoff',
    insufficient_outcome_samples: 'evaluationCodeInsufficientOutcomeSamples',
    outcome_uncertainty_not_ready: 'evaluationCodeOutcomeUncertaintyNotReady',
    incomplete_input_audit: 'evaluationCodeIncompleteInputAudit',
    ready_for_controlled_experiment_design: 'evaluationCodeReadyForExperiment',
    repair_temporal_evidence: 'evaluationCodeRepairTemporalEvidence',
    repair_input_audit: 'evaluationCodeRepairInputAudit',
    investigate_persistent_underperformance: 'evaluationCodeInvestigatePersistent',
    investigate_recent_deterioration: 'evaluationCodeInvestigateRecent',
    design_controlled_challenger: 'evaluationCodeDesignChallenger',
    incomplete_cost_observability: 'evaluationCodeIncompleteCostObservability',
    insufficient_cost_history: 'evaluationCodeInsufficientCostHistory',
    reliability_attention_required: 'evaluationCodeReliabilityAttention',
    recent_cost_increase_observed: 'evaluationCodeRecentCostIncrease',
    cost_baseline_ready: 'evaluationCodeCostBaselineReady',
    repair_cost_observability: 'evaluationCodeRepairCostObservability',
    continue_cost_collection: 'evaluationCodeContinueCostCollection',
    investigate_run_reliability: 'evaluationCodeInvestigateRunReliability',
    investigate_recent_cost_increase: 'evaluationCodeInvestigateCostIncrease',
    monitor_cost_and_design_challenger: 'evaluationCodeMonitorCost',
    awaiting_first_active_run: 'evaluationCodeAwaitingFirstActiveRun',
    active_run_requires_attention: 'evaluationCodeActiveRunNeedsAttention',
    awaiting_outcome_maturity: 'evaluationCodeAwaitingOutcomeMaturity',
    active_outcome_observed: 'evaluationCodeActiveOutcomeObserved',
    historical_architecture: 'evaluationCodeHistoricalArchitecture',
    architecture_identity_not_observed: 'evaluationCodeArchitectureIdentityUnknown',
    scheduled_architecture_disabled: 'evaluationCodeArchitectureScheduleDisabled',
    active_architecture_inventory_unavailable: 'evaluationCodeArchitectureInventoryUnavailable',
    cross_ticker_outcome_aggregate: 'evaluationCodeCrossTickerAggregate',
    awaiting_initial_run: 'evaluationCodeAwaitingInitialRun',
    repair_before_measurement: 'evaluationCodeRepairBeforeMeasurement',
    outcome_collection_in_progress: 'evaluationCodeOutcomeCollectionInProgress',
    minimum_outcome_sample_reached: 'evaluationCodeMinimumOutcomeReached',
    collect_first_active_run_without_decision_changes: 'evaluationCodeCollectFirstStableRun',
    repair_active_run_before_experiment: 'evaluationCodeRepairActiveRunFirst',
    hold_architecture_for_outcome_maturity: 'evaluationCodeHoldForOutcomeMaturity',
    continue_active_outcome_collection: 'evaluationCodeContinueActiveOutcomes',
    review_active_architecture_assessment: 'evaluationCodeReviewActiveAssessment',
  };

  function codeLabel(value) {
    const normalized = String(value || 'not_observed');
    const key = codeKeys[normalized];
    return key ? t(key) : normalized.replaceAll('_', ' ');
  }

  function number(value, digits = 4) {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat(locale(), {
      maximumFractionDigits: digits,
      minimumFractionDigits: Math.min(2, digits),
    }).format(value);
  }

  function percent(value) {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat(locale(), {
      style: 'percent',
      maximumFractionDigits: 1,
    }).format(value);
  }

  function metric(label, value) {
    const card = element('div', 'evaluation-summary-card');
    card.append(
      element('span', 'evaluation-summary-label', label),
      element('strong', 'evaluation-summary-value', value),
    );
    return card;
  }

  function renderSummary(view) {
    summaryElement.replaceChildren(
      metric(t('evaluatedResults'), view.evaluationCount),
      metric(t('pendingResults'), view.pendingCount),
      metric(t('architectureCohorts'), view.cohortCount),
      metric(t('activeArchitectures'), view.activeArchitectureCount),
      metric(t('costRuns'), view.runCostSampleCount),
    );
  }

  function rollingTable(rows) {
    const wrapper = element('div', 'evaluation-table-wrap');
    const table = element('table', 'evaluation-table');
    const head = element('thead');
    const headRow = element('tr');
    [
      t('evaluationTicker'),
      t('rollingWindow'),
      t('current'),
      t('previous'),
      t('change'),
    ].forEach(label => headRow.append(element('th', null, label)));
    head.append(headRow);
    const body = element('tbody');
    rows.forEach(row => {
      const tr = element('tr');
      tr.append(
        element('td', null, row.ticker),
        element('td', null, `${row.windowSize}`),
        element('td', null, `${number(row.currentMeanScore)} · n=${row.currentCount}`),
        element('td', null, number(row.previousMeanScore)),
        element(
          'td',
          row.scoreDelta === null
            ? 'evaluation-neutral'
            : row.scoreDelta >= 0
              ? 'evaluation-positive'
              : 'evaluation-negative',
          row.status === 'comparison_ready' ? number(row.scoreDelta) : '—',
        ),
      );
      body.append(tr);
    });
    table.append(head, body);
    wrapper.append(table);
    return wrapper;
  }

  function costRollingTable(rows) {
    const wrapper = element('div', 'evaluation-table-wrap');
    const table = element('table', 'evaluation-table');
    const head = element('thead');
    const headRow = element('tr');
    [
      t('rollingWindow'),
      t('currentDailyTokens'),
      t('previousDailyTokens'),
      t('change'),
      t('costWindowStatus'),
    ].forEach(label => headRow.append(element('th', null, label)));
    head.append(headRow);
    const body = element('tbody');
    rows.forEach(row => {
      const tr = element('tr');
      tr.append(
        element('td', null, `${row.windowSize}`),
        element(
          'td',
          null,
          `${number(row.currentMeanTokensIn, 0)} · ${row.currentDateCount}d/${row.currentRunCount}r`,
        ),
        element('td', null, number(row.previousMeanTokensIn, 0)),
        element(
          'td',
          row.tokenDelta === null
            ? 'evaluation-neutral'
            : row.tokenDelta <= 0
              ? 'evaluation-positive'
              : 'evaluation-negative',
          row.status === 'comparison_ready'
            ? `${number(row.tokenDelta, 0)} (${percent(row.tokenDeltaRatio)})`
            : '—',
        ),
        element('td', null, codeLabel(row.status)),
      );
      body.append(tr);
    });
    table.append(head, body);
    wrapper.append(table);
    return wrapper;
  }

  function renderRollups(view) {
    if (!view.cohorts.length) {
      rollupsElement.replaceChildren(element('p', 'evaluation-empty', t('noEvaluations')));
      return;
    }
    rollupsElement.replaceChildren(...view.cohorts.map(cohort => {
      const card = element('article', 'evaluation-card');
      const header = element('div', 'evaluation-card-header');
      const title = element('div');
      title.append(
        element(
          'h3',
          null,
          cohort.ticker ? `${cohort.ticker} · ${cohort.version}` : cohort.version,
        ),
        element('p', 'evaluation-fingerprint', `${t('fingerprint')}: ${shortFingerprint(cohort.fingerprint)}`),
      );
      header.append(
        title,
        element(
          'span',
          'evaluation-status-badge',
          codeLabel(cohort.architectureStatus),
        ),
      );
      const metrics = element('div', 'evaluation-metrics');
      metrics.append(
        metric(t('samples'), cohort.sampleCount),
        metric(t('hitRate'), percent(cohort.hitRate)),
        metric(t('meanAlpha'), percent(cohort.meanAlpha)),
        metric(t('meanScore'), number(cohort.meanScore)),
        metric(t('costRuns'), cohort.costSampleCount),
      );
      card.append(header, metrics);
      const diagnostic = element('div', 'evaluation-diagnostic');
      diagnostic.append(
        element('h4', null, t('optimizationDiagnostic')),
        comparisonRow(
          t('architectureLifecycle'),
          codeLabel(cohort.architectureStatus),
        ),
        comparisonRow(
          t('outcomeStatus'),
          codeLabel(cohort.outcomeStatus),
        ),
        comparisonRow(
          t('experimentReadiness'),
          codeLabel(cohort.optimization.readinessStatus),
        ),
        comparisonRow(
          t('recommendedAction'),
          codeLabel(cohort.optimization.recommendedAction),
        ),
        comparisonRow(
          t('controlledExperimentReady'),
          t(cohort.optimization.controlledExperimentReady ? 'yes' : 'no'),
        ),
      );
      if (cohort.measurementContinuity) {
        diagnostic.append(
          comparisonRow(
            t('measurementContinuity'),
            codeLabel(cohort.measurementContinuity.status),
          ),
          comparisonRow(
            t('continuityRecommendedAction'),
            codeLabel(cohort.measurementContinuity.recommendedAction),
          ),
          comparisonRow(
            t('activeOutcomeProgress'),
            `${cohort.activeOutcomeSampleCount}/${cohort.measurementContinuity.minimumOutcomeSamples}`,
          ),
          comparisonRow(
            t('safetyFixesOverrideContinuity'),
            t(cohort.measurementContinuity.safetyOverride ? 'yes' : 'no'),
          ),
        );
      }
      if (cohort.costSampleCount) {
        diagnostic.append(
          comparisonRow(
            t('costDiagnostic'),
            codeLabel(cohort.costAssessment.status),
          ),
          comparisonRow(
            t('costRecommendedAction'),
            codeLabel(cohort.costAssessment.recommendedAction),
          ),
          comparisonRow(
            t('costAnalysisDates'),
            cohort.costAssessment.distinctAnalysisDateCount,
          ),
          comparisonRow(
            t('statsCoverage'),
            `${cohort.costStatsObservedCount}/${cohort.costSampleCount}`,
          ),
          comparisonRow(
            t('runStatuses'),
            Object.entries(cohort.runStatusCounts)
              .map(([status, count]) => `${status}: ${count}`)
              .join(' · '),
          ),
        );
      }
      if (cohort.optimization.costHotspots.length) {
        diagnostic.append(comparisonRow(
          t('costHotspots'),
          cohort.optimization.costHotspots
            .map(item => `${item.agent} (${number(item.meanTokensIn, 0)})`)
            .join(' · '),
        ));
      }
      if (cohort.optimization.toolContextHotspots.length) {
        diagnostic.append(comparisonRow(
          t('toolContextHotspots'),
          cohort.optimization.toolContextHotspots
            .map(item => `${item.tool} (${number(item.meanOutputChars, 0)})`)
            .join(' · '),
        ));
      }
      if (cohort.optimization.weakestRating) {
        const weakest = cohort.optimization.weakestRating;
        diagnostic.append(comparisonRow(
          t('weakestRating'),
          `${weakest.rating} · ${number(weakest.meanScore)} · n=${weakest.sampleCount}`,
        ));
      }
      card.append(diagnostic);
      if (cohort.rolling.length) card.append(rollingTable(cohort.rolling));
      if (cohort.costRolling.length) {
        card.append(
          element('h4', null, t('rollingCostMonitoring')),
          costRollingTable(cohort.costRolling),
        );
      }
      return card;
    }));
  }

  function renderPending(view) {
    if (!view.pending.length) {
      pendingElement.replaceChildren(element('p', 'evaluation-empty', t('noPendingEvaluations')));
      return;
    }
    const list = element('ol', 'evaluation-pending-list');
    view.pending.slice(0, 20).forEach(row => {
      const item = element('li');
      item.append(
        element('strong', null, `${row.ticker || '—'} · ${row.analysis_date || '—'}`),
        element(
          'span',
          null,
          `${row.architecture_version || 'unknown'} · ${
            row.status === 'blocked_invalid_history'
              ? `${t('settlementBlocked')} (${row.settlement_issue_code || 'unknown'})`
              : row.status === 'settlement_in_progress'
              ? t('settlementInProgress')
              : t('awaitingOutcome')
          }`,
        ),
      );
      list.append(item);
    });
    pendingElement.replaceChildren(list);
  }

  function populateComparison(view) {
    const previousBaseline = baselineField.value;
    const previousChallenger = challengerField.value;
    const comparableCohorts = view.cohorts.filter(cohort => cohort.sampleCount > 0);
    const options = comparableCohorts.map(cohort => {
      const option = element(
        'option',
        null,
        `${cohort.version} · ${shortFingerprint(cohort.fingerprint)}`,
      );
      option.value = cohort.key;
      return option;
    });
    baselineField.replaceChildren(...options.map(option => option.cloneNode(true)));
    challengerField.replaceChildren(...options.map(option => option.cloneNode(true)));
    const keys = new Set(comparableCohorts.map(cohort => cohort.key));
    baselineField.value = keys.has(previousBaseline)
      ? previousBaseline
      : (comparableCohorts[0]?.key || '');
    challengerField.value = keys.has(previousChallenger)
      ? previousChallenger
      : (comparableCohorts.find(
        cohort => cohort.version !== comparableCohorts[0]?.version,
      )?.key || '');
    compareButton.disabled = !baselineField.value || !challengerField.value;
  }

  function comparisonRow(label, value) {
    const row = element('div', 'evaluation-comparison-row');
    row.append(element('span', null, label), element('strong', null, value));
    return row;
  }

  function renderComparison(comparison) {
    if (!comparison) {
      comparisonElement.replaceChildren(
        element('p', 'evaluation-empty', t('comparisonUnavailable')),
      );
      return;
    }
    const assessment = comparison.optimization_assessment || {};
    const rows = [
      comparisonRow(t('assessmentStatus'), codeLabel(comparison.status)),
      comparisonRow(
        t('experimentIntegrity'),
        codeLabel(assessment.experiment_integrity?.status),
      ),
      comparisonRow(
        t('outcomeEvidence'),
        codeLabel(assessment.outcome_evidence?.status),
      ),
      comparisonRow(
        t('costEvidence'),
        codeLabel(assessment.cost_evidence?.status),
      ),
      comparisonRow(
        t('validPairs'),
        assessment.experiment_integrity?.valid_pair_count ?? 0,
      ),
      comparisonRow(
        t('recommendedAction'),
        codeLabel(assessment.recommended_action || 'continue_sample_collection'),
      ),
    ];
    const toolHotspots = Array.isArray(assessment.tool_context_hotspots)
      ? assessment.tool_context_hotspots.slice(0, 3)
      : [];
    if (toolHotspots.length) {
      rows.push(comparisonRow(
        t('pairedToolContextHotspots'),
        toolHotspots.map(item => (
          `${String(item.tool || 'unknown')} (Δ${number(finiteNumber(item.mean_delta), 0)})`
        )).join(' · '),
      ));
    }
    rows.push(element('p', 'evaluation-safety-note', t('automaticMutationDisabled')));
    comparisonElement.replaceChildren(...rows);
  }

  function render(payload) {
    cachedPayload = payload;
    const view = buildEvaluationViewModel(payload);
    renderSummary(view);
    renderRollups(view);
    renderPending(view);
    populateComparison(view);
    renderComparison(view.comparison);
    statusElement.textContent = '';
  }

  async function load() {
    statusElement.textContent = t('loadingEvaluations');
    try {
      render(await api.getEvaluations({ ticker: tickerField.value.trim() }));
    } catch (error) {
      statusElement.textContent = `${t('evaluationLoadFailed')}: ${error.message}`;
    }
  }

  async function compare() {
    const view = buildEvaluationViewModel(cachedPayload || {});
    const byKey = new Map(view.cohorts.map(cohort => [cohort.key, cohort]));
    const baseline = byKey.get(baselineField.value);
    const challenger = byKey.get(challengerField.value);
    if (!baseline || !challenger || baseline.version === challenger.version) {
      comparisonElement.replaceChildren(
        element('p', 'evaluation-empty', t('comparisonRequiresDistinct')),
      );
      return;
    }
    compareButton.disabled = true;
    try {
      const payload = await api.getEvaluations({
        ticker: tickerField.value.trim(),
        baseline: baseline.version,
        challenger: challenger.version,
        baselineFingerprint: baseline.fingerprint,
        challengerFingerprint: challenger.fingerprint,
      });
      cachedPayload = payload;
      renderComparison(payload.comparison);
    } catch (error) {
      comparisonElement.replaceChildren(
        element('p', 'evaluation-empty', `${t('evaluationLoadFailed')}: ${error.message}`),
      );
    } finally {
      compareButton.disabled = false;
    }
  }

  function relocalize() {
    if (cachedPayload) render(cachedPayload);
  }

  return { load, compare, relocalize };
}

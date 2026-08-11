/**
 * The badge class an outcome is worth, which is only ever three answers.
 *
 * Shared by the run page and the history table because a stage that reads as
 * finished in one place and as running in the other is worse than either
 * answer. Adding a stage to the pipeline is then one edit rather than two that
 * have to be remembered together.
 *
 * A refusal is a verdict about the song rather than a fault, so it gets the
 * neutral badge and says the rest in its own words. So does an unknown stage
 * from a newer pipeline: as far as these two views are concerned it is still
 * in progress.
 */
export function stageTone(stage: string): string {
  if (stage === 'done') {
    return 'badge--ok';
  }
  if (stage === 'failed') {
    return 'badge--bad';
  }
  return stage === 'refused' ? '' : 'badge--busy';
}

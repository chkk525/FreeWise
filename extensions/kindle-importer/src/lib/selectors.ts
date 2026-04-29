import sharedSelectors from '../../../../shared/kindle-selectors.json';

export type KindleSelectors = typeof sharedSelectors;
export const SELECTORS = sharedSelectors as KindleSelectors;

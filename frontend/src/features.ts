/** Runtime rollout controls. Flags are intentionally public and only affect
 * presentation; backend authorization remains authoritative. */
export const featureFlags = {
  advancedOperations: import.meta.env.VITE_ENABLE_ADVANCED_OPERATIONS !== 'false',
  organizationAdministration: import.meta.env.VITE_ENABLE_ORGANIZATION_ADMIN !== 'false',
  deploymentControls: import.meta.env.VITE_ENABLE_DEPLOYMENT_CONTROLS !== 'false',
} as const

export type FeatureFlag = keyof typeof featureFlags
export const isFeatureEnabled = (flag: FeatureFlag) => featureFlags[flag]

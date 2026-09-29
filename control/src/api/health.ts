export type HealthResponse = {
  status: string
  service: string
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch('/health')
  if (!response.ok) {
    throw new Error(`RaceCore API returned ${response.status}`)
  }
  return response.json() as Promise<HealthResponse>
}

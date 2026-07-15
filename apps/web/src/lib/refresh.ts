import { queryClient } from "./queryClient";

export async function refreshWorkspace(projectId: string): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["project-files", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["project-papers", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["citation-neighborhood"] }),
    queryClient.invalidateQueries({ queryKey: ["project-graph", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["paper-search", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["projects"] }),
  ]);
}

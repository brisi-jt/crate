"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import { type Me, meSchema } from "@/lib/api/schemas";

/** The current user — birth year drives the era strip's coming-of-age band. */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async (): Promise<Me> =>
      meSchema.parse(await request<unknown>("GET", "/v1/me")),
    staleTime: 10 * 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

/**
 * Set (or clear) the birth year. Optimistic: the readout flips immediately;
 * a failure rolls back. Settling invalidates both /me and the survey, since
 * eras.coming_of_age and coverage.birth_year_set derive from it server-side.
 */
export function useSetBirthYear() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (birthYear: number | null): Promise<Me> =>
      meSchema.parse(
        await request<unknown>("PATCH", "/v1/me", {
          body: { birth_year: birthYear },
        }),
      ),
    onMutate: async (birthYear) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.me });
      const previous = queryClient.getQueryData<Me>(queryKeys.me);
      if (previous) {
        queryClient.setQueryData<Me>(queryKeys.me, {
          ...previous,
          birth_year: birthYear,
        });
      }
      return { previous };
    },
    onError: (_error, _birthYear, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.me, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
      queryClient.invalidateQueries({ queryKey: queryKeys.insights });
    },
  });
}

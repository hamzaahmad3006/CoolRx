import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

import type {
  AgentTraceResponse,
  AttributionResponse,
  CandidatesResponse,
  CounterfactualResponse,
  CreatePlanRequest,
  CreatePlanResponse,
  CreateProjectRequest,
  CreateProjectResponse,
  CreditsResponse,
  DiagnoseRequest,
  DiagnoseResponse,
  ExposureResponse,
  FgAnalyticType,
  GetPlanResponse,
  HealthResponse,
  JobResponse,
  ListProjectsResponse,
  ModelValidationResponse,
  PriorityResponse,
  Project,
  ProvenanceResponse,
  StatsResponse,
  TilesResponse,
  VerificationProtocolResponse,
  VerifyRequest,
  VerifyResponse,
} from '@/types';

/**
 * CoolRx server-data layer.
 *
 * RTK Query owns all server state: caching, request de-duplication, tag-based
 * invalidation, and polling for the asynchronous FortyGuard jobs. Redux slices
 * hold only ephemeral client state.
 *
 * The FortyGuard API key never appears here — every call goes to the CoolRx
 * backend, which holds the credential server-side (SRS §18.1).
 */
export const coolRxApi = createApi({
  reducerPath: 'coolRxApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'}/api`,
    prepareHeaders: (headers) => {
      // Gate for credit-spending endpoints. Public reads need no header.
      const demoKey = process.env.NEXT_PUBLIC_DEMO_KEY;
      if (demoKey !== undefined && demoKey !== '') {
        headers.set('X-Demo-Key', demoKey);
      }
      return headers;
    },
  }),
  tagTypes: ['Project', 'Diagnosis', 'Plan', 'Job', 'Verification', 'System'],
  endpoints: (build) => ({
    /* ── Projects ──────────────────────────────────────────────────────── */
    listProjects: build.query<ListProjectsResponse, void>({
      query: () => 'projects',
      providesTags: ['Project'],
    }),

    getProject: build.query<Project, string>({
      query: (projectId) => `projects/${projectId}`,
      providesTags: (_result, _error, projectId) => [
        { type: 'Project', id: projectId },
      ],
    }),

    createProject: build.mutation<CreateProjectResponse, CreateProjectRequest>({
      query: (body) => ({ url: 'projects', method: 'POST', body }),
      invalidatesTags: ['Project'],
    }),

    /* ── Diagnosis (async job) ─────────────────────────────────────────── */
    startDiagnosis: build.mutation<
      DiagnoseResponse,
      { readonly projectId: string; readonly body: DiagnoseRequest }
    >({
      query: ({ projectId, body }) => ({
        url: `projects/${projectId}/diagnose`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Job'],
    }),

    /**
     * Job status. FortyGuard tasks take minutes, so this polls while running and
     * stops once the job reaches a terminal state.
     */
    getJob: build.query<JobResponse, string>({
      query: (jobId) => `jobs/${jobId}`,
      providesTags: (_result, _error, jobId) => [{ type: 'Job', id: jobId }],
    }),

    /* ── Diagnosis results ─────────────────────────────────────────────── */
    getTiles: build.query<
      TilesResponse,
      { readonly projectId: string; readonly analytic: FgAnalyticType }
    >({
      query: ({ projectId, analytic }) =>
        `projects/${projectId}/tiles?analytic=${analytic}&simplify=auto`,
      providesTags: (_result, _error, arg) => [
        { type: 'Diagnosis', id: `${arg.projectId}:${arg.analytic}` },
      ],
    }),

    getStats: build.query<StatsResponse, string>({
      query: (projectId) => `projects/${projectId}/stats`,
      providesTags: (_r, _e, projectId) => [{ type: 'Diagnosis', id: projectId }],
    }),

    getAttribution: build.query<AttributionResponse, string>({
      query: (projectId) => `projects/${projectId}/attribution`,
      providesTags: (_r, _e, projectId) => [{ type: 'Diagnosis', id: projectId }],
    }),

    getExposure: build.query<ExposureResponse, string>({
      query: (projectId) => `projects/${projectId}/exposure`,
      providesTags: (_r, _e, projectId) => [{ type: 'Diagnosis', id: projectId }],
    }),

    getPriorities: build.query<
      PriorityResponse,
      { readonly projectId: string; readonly equityLambda: number }
    >({
      query: ({ projectId, equityLambda }) =>
        `projects/${projectId}/priorities?equity_lambda=${equityLambda}`,
    }),

    getCandidates: build.query<CandidatesResponse, string>({
      query: (projectId) => `projects/${projectId}/candidates`,
    }),

    /* ── Plans ─────────────────────────────────────────────────────────── */
    createPlan: build.mutation<
      CreatePlanResponse,
      { readonly projectId: string; readonly body: CreatePlanRequest }
    >({
      query: ({ projectId, body }) => ({
        url: `projects/${projectId}/plans`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Plan'],
    }),

    getPlan: build.query<GetPlanResponse, string>({
      query: (planId) => `plans/${planId}`,
      providesTags: (_r, _e, planId) => [{ type: 'Plan', id: planId }],
    }),

    getCounterfactual: build.query<CounterfactualResponse, string>({
      query: (planId) => `plans/${planId}/counterfactual`,
      providesTags: (_r, _e, planId) => [{ type: 'Plan', id: planId }],
    }),

    getProvenance: build.query<ProvenanceResponse, string>({
      query: (planId) => `plans/${planId}/provenance`,
    }),

    /* ── Verification ──────────────────────────────────────────────────── */
    getVerificationProtocol: build.query<VerificationProtocolResponse, string>({
      query: (planId) => `plans/${planId}/verification`,
      providesTags: (_r, _e, planId) => [{ type: 'Verification', id: planId }],
    }),

    runVerification: build.mutation<
      VerifyResponse,
      { readonly planId: string; readonly body: VerifyRequest }
    >({
      query: ({ planId, body }) => ({
        url: `plans/${planId}/verify`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Verification'],
    }),

    /* ── System ────────────────────────────────────────────────────────── */
    getAgentTrace: build.query<AgentTraceResponse, string>({
      query: (runId) => `agent/runs/${runId}/trace`,
    }),

    getModelValidation: build.query<ModelValidationResponse, void>({
      query: () => 'model/validation',
      providesTags: ['System'],
    }),

    getCredits: build.query<CreditsResponse, void>({
      query: () => 'credits',
      providesTags: ['System'],
    }),

    getHealth: build.query<HealthResponse, void>({
      query: () => 'health',
      providesTags: ['System'],
    }),
  }),
});

export const {
  useListProjectsQuery,
  useGetProjectQuery,
  useCreateProjectMutation,
  useStartDiagnosisMutation,
  useGetJobQuery,
  useGetTilesQuery,
  useGetStatsQuery,
  useGetAttributionQuery,
  useGetExposureQuery,
  useGetPrioritiesQuery,
  useGetCandidatesQuery,
  useCreatePlanMutation,
  useGetPlanQuery,
  useGetCounterfactualQuery,
  useGetProvenanceQuery,
  useGetVerificationProtocolQuery,
  useRunVerificationMutation,
  useGetAgentTraceQuery,
  useGetModelValidationQuery,
  useGetCreditsQuery,
  useGetHealthQuery,
} = coolRxApi;

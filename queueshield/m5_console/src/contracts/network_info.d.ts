/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface GET8004V1Network {
  mode: "live" | "mock";
  channel: string;
  chaincode: {
    name?: string;
    version?: string;
    sequence?: number;
  };
  height: number;
  orgs: {
    mspId?: string;
    role?: "PAYER_SIDE_AND_AUTHORITY" | "PAYEE_SIDE" | "AUTHORITY";
    litePeers?: string[];
    committingPeers?: string[];
    validationServices?: string[];
    stateDb?: string;
    transientStore?: string;
  }[];
  orderers?: string[];
  submitLatencyMs?: {
    p50?: number;
    p95?: number;
    p99?: number;
  };
  updated_wall_iso?: string;
}

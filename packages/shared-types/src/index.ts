export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      agent_artifacts: {
        Row: {
          created_at: string | null
          expires_at: string | null
          id: string
          pinned: boolean | null
          session_id: string
          spec_jsonb: Json
          title: string | null
          type: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          expires_at?: string | null
          id?: string
          pinned?: boolean | null
          session_id: string
          spec_jsonb: Json
          title?: string | null
          type: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          expires_at?: string | null
          id?: string
          pinned?: boolean | null
          session_id?: string
          spec_jsonb?: Json
          title?: string | null
          type?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_artifacts_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "chat_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      areas: {
        Row: {
          code: string
          id: string
          name_en: string
          name_jp: string | null
          timezone: string | null
          tso: string | null
        }
        Insert: {
          code: string
          id?: string
          name_en: string
          name_jp?: string | null
          timezone?: string | null
          tso?: string | null
        }
        Update: {
          code?: string
          id?: string
          name_en?: string
          name_jp?: string | null
          timezone?: string | null
          tso?: string | null
        }
        Relationships: []
      }
      assets: {
        Row: {
          area_id: string
          asset_type: string
          commissioned: string | null
          created_at: string | null
          degradation_jpy_mwh: number | null
          energy_mwh: number
          id: string
          max_cycles_per_year: number | null
          metadata: Json | null
          name: string
          portfolio_id: string
          power_mw: number
          round_trip_eff: number
          soc_max_pct: number | null
          soc_min_pct: number | null
          user_id: string
        }
        Insert: {
          area_id: string
          asset_type: string
          commissioned?: string | null
          created_at?: string | null
          degradation_jpy_mwh?: number | null
          energy_mwh: number
          id?: string
          max_cycles_per_year?: number | null
          metadata?: Json | null
          name: string
          portfolio_id: string
          power_mw: number
          round_trip_eff: number
          soc_max_pct?: number | null
          soc_min_pct?: number | null
          user_id: string
        }
        Update: {
          area_id?: string
          asset_type?: string
          commissioned?: string | null
          created_at?: string | null
          degradation_jpy_mwh?: number | null
          energy_mwh?: number
          id?: string
          max_cycles_per_year?: number | null
          metadata?: Json | null
          name?: string
          portfolio_id?: string
          power_mw?: number
          round_trip_eff?: number
          soc_max_pct?: number | null
          soc_min_pct?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "assets_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "assets_portfolio_id_fkey"
            columns: ["portfolio_id"]
            isOneToOne: false
            referencedRelation: "portfolios"
            referencedColumns: ["id"]
          },
        ]
      }
      backtests: {
        Row: {
          asset_id: string
          completed_at: string | null
          created_at: string | null
          error: string | null
          id: string
          max_drawdown_jpy: number | null
          model_id: string | null
          modelled_pnl_jpy: number | null
          realised_pnl_jpy: number | null
          sharpe: number | null
          slippage_jpy: number | null
          status: string
          strategy: string
          trades_jsonb: Json | null
          user_id: string
          window_end: string
          window_start: string
        }
        Insert: {
          asset_id: string
          completed_at?: string | null
          created_at?: string | null
          error?: string | null
          id?: string
          max_drawdown_jpy?: number | null
          model_id?: string | null
          modelled_pnl_jpy?: number | null
          realised_pnl_jpy?: number | null
          sharpe?: number | null
          slippage_jpy?: number | null
          status?: string
          strategy: string
          trades_jsonb?: Json | null
          user_id: string
          window_end: string
          window_start: string
        }
        Update: {
          asset_id?: string
          completed_at?: string | null
          created_at?: string | null
          error?: string | null
          id?: string
          max_drawdown_jpy?: number | null
          model_id?: string | null
          modelled_pnl_jpy?: number | null
          realised_pnl_jpy?: number | null
          sharpe?: number | null
          slippage_jpy?: number | null
          status?: string
          strategy?: string
          trades_jsonb?: Json | null
          user_id?: string
          window_end?: string
          window_start?: string
        }
        Relationships: [
          {
            foreignKeyName: "backtests_asset_id_fkey"
            columns: ["asset_id"]
            isOneToOne: false
            referencedRelation: "assets"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "backtests_model_id_fkey"
            columns: ["model_id"]
            isOneToOne: false
            referencedRelation: "models"
            referencedColumns: ["id"]
          },
        ]
      }
      chat_messages: {
        Row: {
          content: string
          created_at: string | null
          id: string
          role: string
          session_id: string
          tokens_in: number | null
          tokens_out: number | null
          tool_calls: Json | null
          tool_results: Json | null
        }
        Insert: {
          content: string
          created_at?: string | null
          id?: string
          role: string
          session_id: string
          tokens_in?: number | null
          tokens_out?: number | null
          tool_calls?: Json | null
          tool_results?: Json | null
        }
        Update: {
          content?: string
          created_at?: string | null
          id?: string
          role?: string
          session_id?: string
          tokens_in?: number | null
          tokens_out?: number | null
          tool_calls?: Json | null
          tool_results?: Json | null
        }
        Relationships: [
          {
            foreignKeyName: "chat_messages_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "chat_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      chat_sessions: {
        Row: {
          created_at: string | null
          id: string
          title: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          title?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          title?: string | null
          user_id?: string
        }
        Relationships: []
      }
      compute_runs: {
        Row: {
          created_at: string | null
          duration_ms: number | null
          error: string | null
          id: string
          input: Json | null
          kind: string
          output: Json | null
          status: string
          user_id: string | null
        }
        Insert: {
          created_at?: string | null
          duration_ms?: number | null
          error?: string | null
          id?: string
          input?: Json | null
          kind: string
          output?: Json | null
          status: string
          user_id?: string | null
        }
        Update: {
          created_at?: string | null
          duration_ms?: number | null
          error?: string | null
          id?: string
          input?: Json | null
          kind?: string
          output?: Json | null
          status?: string
          user_id?: string | null
        }
        Relationships: []
      }
      data_dictionary: {
        Row: {
          column_name: string
          description: string
          notes: string | null
          table_name: string
          unit: string | null
        }
        Insert: {
          column_name: string
          description: string
          notes?: string | null
          table_name: string
          unit?: string | null
        }
        Update: {
          column_name?: string
          description?: string
          notes?: string | null
          table_name?: string
          unit?: string | null
        }
        Relationships: []
      }
      demand_actuals: {
        Row: {
          area_id: string
          demand_mw: number | null
          ingested_at: string | null
          slot_start: string
          source: string
        }
        Insert: {
          area_id: string
          demand_mw?: number | null
          ingested_at?: string | null
          slot_start: string
          source: string
        }
        Update: {
          area_id?: string
          demand_mw?: number | null
          ingested_at?: string | null
          slot_start?: string
          source?: string
        }
        Relationships: [
          {
            foreignKeyName: "demand_actuals_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
        ]
      }
      forecast_paths: {
        Row: {
          forecast_run_id: string
          path_id: number
          price_jpy_kwh: number
          slot_start: string
        }
        Insert: {
          forecast_run_id: string
          path_id: number
          price_jpy_kwh: number
          slot_start: string
        }
        Update: {
          forecast_run_id?: string
          path_id?: number
          price_jpy_kwh?: number
          slot_start?: string
        }
        Relationships: [
          {
            foreignKeyName: "forecast_paths_forecast_run_id_fkey"
            columns: ["forecast_run_id"]
            isOneToOne: false
            referencedRelation: "forecast_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      forecast_runs: {
        Row: {
          area_id: string
          created_at: string | null
          forecast_origin: string
          horizon_slots: number
          id: string
          model_id: string
          n_paths: number
        }
        Insert: {
          area_id: string
          created_at?: string | null
          forecast_origin: string
          horizon_slots: number
          id?: string
          model_id: string
          n_paths: number
        }
        Update: {
          area_id?: string
          created_at?: string | null
          forecast_origin?: string
          horizon_slots?: number
          id?: string
          model_id?: string
          n_paths?: number
        }
        Relationships: [
          {
            foreignKeyName: "forecast_runs_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "forecast_runs_model_id_fkey"
            columns: ["model_id"]
            isOneToOne: false
            referencedRelation: "models"
            referencedColumns: ["id"]
          },
        ]
      }
      fuel_prices: {
        Row: {
          fuel_type_id: string
          ingested_at: string | null
          price: number
          source: string
          ts: string
          unit: string
        }
        Insert: {
          fuel_type_id: string
          ingested_at?: string | null
          price: number
          source: string
          ts: string
          unit: string
        }
        Update: {
          fuel_type_id?: string
          ingested_at?: string | null
          price?: number
          source?: string
          ts?: string
          unit?: string
        }
        Relationships: [
          {
            foreignKeyName: "fuel_prices_fuel_type_id_fkey"
            columns: ["fuel_type_id"]
            isOneToOne: false
            referencedRelation: "fuel_types"
            referencedColumns: ["id"]
          },
        ]
      }
      fuel_types: {
        Row: {
          code: string
          id: string
          name_en: string
        }
        Insert: {
          code: string
          id?: string
          name_en: string
        }
        Update: {
          code?: string
          id?: string
          name_en?: string
        }
        Relationships: []
      }
      fx_rates: {
        Row: {
          pair: string
          rate: number
          source: string
          ts: string
        }
        Insert: {
          pair: string
          rate: number
          source: string
          ts: string
        }
        Update: {
          pair?: string
          rate?: number
          source?: string
          ts?: string
        }
        Relationships: []
      }
      generation_mix_actuals: {
        Row: {
          area_id: string
          curtailment_mw: number | null
          fuel_type_id: string
          ingested_at: string | null
          output_mw: number | null
          slot_start: string
          source: string
        }
        Insert: {
          area_id: string
          curtailment_mw?: number | null
          fuel_type_id: string
          ingested_at?: string | null
          output_mw?: number | null
          slot_start: string
          source: string
        }
        Update: {
          area_id?: string
          curtailment_mw?: number | null
          fuel_type_id?: string
          ingested_at?: string | null
          output_mw?: number | null
          slot_start?: string
          source?: string
        }
        Relationships: [
          {
            foreignKeyName: "generation_mix_actuals_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "generation_mix_actuals_fuel_type_id_fkey"
            columns: ["fuel_type_id"]
            isOneToOne: false
            referencedRelation: "fuel_types"
            referencedColumns: ["id"]
          },
        ]
      }
      generator_availability: {
        Row: {
          available_mw: number | null
          generator_id: string
          slot_start: string
          source: string | null
          status: string | null
        }
        Insert: {
          available_mw?: number | null
          generator_id: string
          slot_start: string
          source?: string | null
          status?: string | null
        }
        Update: {
          available_mw?: number | null
          generator_id?: string
          slot_start?: string
          source?: string | null
          status?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "generator_availability_generator_id_fkey"
            columns: ["generator_id"]
            isOneToOne: false
            referencedRelation: "generators"
            referencedColumns: ["id"]
          },
        ]
      }
      generators: {
        Row: {
          area_id: string
          capacity_mw: number
          co2_intensity_t_mwh: number | null
          commissioned: string | null
          efficiency: number | null
          fuel_type_id: string
          heat_rate_kj_kwh: number | null
          id: string
          metadata: Json | null
          name: string
          notes: string | null
          operator: string | null
          retired: string | null
          unit_type_id: string | null
          variable_om_jpy_mwh: number | null
        }
        Insert: {
          area_id: string
          capacity_mw: number
          co2_intensity_t_mwh?: number | null
          commissioned?: string | null
          efficiency?: number | null
          fuel_type_id: string
          heat_rate_kj_kwh?: number | null
          id?: string
          metadata?: Json | null
          name: string
          notes?: string | null
          operator?: string | null
          retired?: string | null
          unit_type_id?: string | null
          variable_om_jpy_mwh?: number | null
        }
        Update: {
          area_id?: string
          capacity_mw?: number
          co2_intensity_t_mwh?: number | null
          commissioned?: string | null
          efficiency?: number | null
          fuel_type_id?: string
          heat_rate_kj_kwh?: number | null
          id?: string
          metadata?: Json | null
          name?: string
          notes?: string | null
          operator?: string | null
          retired?: string | null
          unit_type_id?: string | null
          variable_om_jpy_mwh?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "generators_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "generators_fuel_type_id_fkey"
            columns: ["fuel_type_id"]
            isOneToOne: false
            referencedRelation: "fuel_types"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "generators_unit_type_id_fkey"
            columns: ["unit_type_id"]
            isOneToOne: false
            referencedRelation: "unit_types"
            referencedColumns: ["id"]
          },
        ]
      }
      interconnection_flows: {
        Row: {
          flow_mw: number | null
          from_area_id: string
          ingested_at: string | null
          slot_start: string
          source: string | null
          to_area_id: string
        }
        Insert: {
          flow_mw?: number | null
          from_area_id: string
          ingested_at?: string | null
          slot_start: string
          source?: string | null
          to_area_id: string
        }
        Update: {
          flow_mw?: number | null
          from_area_id?: string
          ingested_at?: string | null
          slot_start?: string
          source?: string | null
          to_area_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "interconnection_flows_from_area_id_fkey"
            columns: ["from_area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "interconnection_flows_to_area_id_fkey"
            columns: ["to_area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
        ]
      }
      jepx_spot_prices: {
        Row: {
          area_id: string
          auction_type: string
          buy_volume_mwh: number | null
          contract_volume_mwh: number | null
          id: number
          ingested_at: string | null
          price_jpy_kwh: number | null
          sell_volume_mwh: number | null
          slot_end: string
          slot_start: string
          source: string
        }
        Insert: {
          area_id: string
          auction_type: string
          buy_volume_mwh?: number | null
          contract_volume_mwh?: number | null
          id?: number
          ingested_at?: string | null
          price_jpy_kwh?: number | null
          sell_volume_mwh?: number | null
          slot_end: string
          slot_start: string
          source: string
        }
        Update: {
          area_id?: string
          auction_type?: string
          buy_volume_mwh?: number | null
          contract_volume_mwh?: number | null
          id?: number
          ingested_at?: string | null
          price_jpy_kwh?: number | null
          sell_volume_mwh?: number | null
          slot_end?: string
          slot_start?: string
          source?: string
        }
        Relationships: [
          {
            foreignKeyName: "jepx_spot_prices_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
        ]
      }
      jp_holidays: {
        Row: {
          category: string | null
          date: string
          name_en: string | null
          name_jp: string | null
        }
        Insert: {
          category?: string | null
          date: string
          name_en?: string | null
          name_jp?: string | null
        }
        Update: {
          category?: string | null
          date?: string
          name_en?: string | null
          name_jp?: string | null
        }
        Relationships: []
      }
      models: {
        Row: {
          artifact_url: string | null
          created_at: string | null
          hyperparams: Json | null
          id: string
          metrics: Json | null
          name: string
          status: string
          training_window_end: string | null
          training_window_start: string | null
          type: string
          version: string
        }
        Insert: {
          artifact_url?: string | null
          created_at?: string | null
          hyperparams?: Json | null
          id?: string
          metrics?: Json | null
          name: string
          status?: string
          training_window_end?: string | null
          training_window_start?: string | null
          type: string
          version: string
        }
        Update: {
          artifact_url?: string | null
          created_at?: string | null
          hyperparams?: Json | null
          id?: string
          metrics?: Json | null
          name?: string
          status?: string
          training_window_end?: string | null
          training_window_start?: string | null
          type?: string
          version?: string
        }
        Relationships: []
      }
      portfolios: {
        Row: {
          created_at: string | null
          description: string | null
          id: string
          name: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          description?: string | null
          id?: string
          name: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          description?: string | null
          id?: string
          name?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      regime_states: {
        Row: {
          area_id: string
          model_version: string
          most_likely_regime: string
          p_base: number
          p_drop: number
          p_spike: number
          slot_start: string
        }
        Insert: {
          area_id: string
          model_version: string
          most_likely_regime: string
          p_base: number
          p_drop: number
          p_spike: number
          slot_start: string
        }
        Update: {
          area_id?: string
          model_version?: string
          most_likely_regime?: string
          p_base?: number
          p_drop?: number
          p_spike?: number
          slot_start?: string
        }
        Relationships: [
          {
            foreignKeyName: "regime_states_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
        ]
      }
      stack_clearing_prices: {
        Row: {
          area_id: string
          created_at: string | null
          marginal_unit_id: string | null
          modelled_demand_mw: number | null
          modelled_price_jpy_mwh: number | null
          slot_start: string
          stack_curve_id: string | null
        }
        Insert: {
          area_id: string
          created_at?: string | null
          marginal_unit_id?: string | null
          modelled_demand_mw?: number | null
          modelled_price_jpy_mwh?: number | null
          slot_start: string
          stack_curve_id?: string | null
        }
        Update: {
          area_id?: string
          created_at?: string | null
          marginal_unit_id?: string | null
          modelled_demand_mw?: number | null
          modelled_price_jpy_mwh?: number | null
          slot_start?: string
          stack_curve_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "stack_clearing_prices_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "stack_clearing_prices_marginal_unit_id_fkey"
            columns: ["marginal_unit_id"]
            isOneToOne: false
            referencedRelation: "generators"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "stack_clearing_prices_stack_curve_id_fkey"
            columns: ["stack_curve_id"]
            isOneToOne: false
            referencedRelation: "stack_curves"
            referencedColumns: ["id"]
          },
        ]
      }
      stack_curves: {
        Row: {
          area_id: string
          created_at: string | null
          curve_jsonb: Json
          id: string
          inputs_hash: string
          slot_start: string
        }
        Insert: {
          area_id: string
          created_at?: string | null
          curve_jsonb: Json
          id?: string
          inputs_hash: string
          slot_start: string
        }
        Update: {
          area_id?: string
          created_at?: string | null
          curve_jsonb?: Json
          id?: string
          inputs_hash?: string
          slot_start?: string
        }
        Relationships: [
          {
            foreignKeyName: "stack_curves_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
        ]
      }
      unit_types: {
        Row: {
          code: string
          id: string
          name_en: string
        }
        Insert: {
          code: string
          id?: string
          name_en: string
        }
        Update: {
          code?: string
          id?: string
          name_en?: string
        }
        Relationships: []
      }
      valuation_decisions: {
        Row: {
          action_mw: number | null
          expected_pnl_jpy: number | null
          slot_start: string
          soc_mwh: number | null
          valuation_id: string
        }
        Insert: {
          action_mw?: number | null
          expected_pnl_jpy?: number | null
          slot_start: string
          soc_mwh?: number | null
          valuation_id: string
        }
        Update: {
          action_mw?: number | null
          expected_pnl_jpy?: number | null
          slot_start?: string
          soc_mwh?: number | null
          valuation_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "valuation_decisions_valuation_id_fkey"
            columns: ["valuation_id"]
            isOneToOne: false
            referencedRelation: "valuations"
            referencedColumns: ["id"]
          },
        ]
      }
      valuations: {
        Row: {
          asset_id: string
          basis_functions: Json | null
          ci_lower_jpy: number | null
          ci_upper_jpy: number | null
          completed_at: string | null
          created_at: string | null
          error: string | null
          extrinsic_value_jpy: number | null
          forecast_run_id: string | null
          horizon_end: string
          horizon_start: string
          id: string
          intrinsic_value_jpy: number | null
          method: string
          n_paths: number | null
          n_volume_grid: number | null
          runtime_seconds: number | null
          status: string
          total_value_jpy: number | null
          user_id: string
        }
        Insert: {
          asset_id: string
          basis_functions?: Json | null
          ci_lower_jpy?: number | null
          ci_upper_jpy?: number | null
          completed_at?: string | null
          created_at?: string | null
          error?: string | null
          extrinsic_value_jpy?: number | null
          forecast_run_id?: string | null
          horizon_end: string
          horizon_start: string
          id?: string
          intrinsic_value_jpy?: number | null
          method: string
          n_paths?: number | null
          n_volume_grid?: number | null
          runtime_seconds?: number | null
          status?: string
          total_value_jpy?: number | null
          user_id: string
        }
        Update: {
          asset_id?: string
          basis_functions?: Json | null
          ci_lower_jpy?: number | null
          ci_upper_jpy?: number | null
          completed_at?: string | null
          created_at?: string | null
          error?: string | null
          extrinsic_value_jpy?: number | null
          forecast_run_id?: string | null
          horizon_end?: string
          horizon_start?: string
          id?: string
          intrinsic_value_jpy?: number | null
          method?: string
          n_paths?: number | null
          n_volume_grid?: number | null
          runtime_seconds?: number | null
          status?: string
          total_value_jpy?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "valuations_asset_id_fkey"
            columns: ["asset_id"]
            isOneToOne: false
            referencedRelation: "assets"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "valuations_forecast_run_id_fkey"
            columns: ["forecast_run_id"]
            isOneToOne: false
            referencedRelation: "forecast_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      weather_obs: {
        Row: {
          area_id: string
          cloud_pct: number | null
          dewpoint_c: number | null
          forecast_horizon_h: number
          ghi_w_m2: number | null
          source: string
          temp_c: number | null
          ts: string
          wind_mps: number | null
        }
        Insert: {
          area_id: string
          cloud_pct?: number | null
          dewpoint_c?: number | null
          forecast_horizon_h?: number
          ghi_w_m2?: number | null
          source: string
          temp_c?: number | null
          ts: string
          wind_mps?: number | null
        }
        Update: {
          area_id?: string
          cloud_pct?: number | null
          dewpoint_c?: number | null
          forecast_horizon_h?: number
          ghi_w_m2?: number | null
          source?: string
          temp_c?: number | null
          ts?: string
          wind_mps?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "weather_obs_area_id_fkey"
            columns: ["area_id"]
            isOneToOne: false
            referencedRelation: "areas"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const

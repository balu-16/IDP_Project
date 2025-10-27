export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  public: {
    Tables: {
      devices: {
        Row: {
          allocated_at: string | null
          allocated_to_customer_id: number | null
          allocated_to_customer_name: string | null
          created_at: string | null
          device_code: string
          device_icon: string | null
          device_m2m_number: string | null
          device_name: string | null
          id: number
          is_active: boolean | null
          qr_code: string
          room_id: number | null
          electronic_object: string | null
          switch_is_active: boolean | null
          switch_created_at: string | null
        }
        Insert: {
          allocated_at?: string | null
          allocated_to_customer_id?: number | null
          allocated_to_customer_name?: string | null
          created_at?: string | null
          device_code: string
          device_icon?: string | null
          device_m2m_number?: string | null
          device_name?: string | null
          id?: number
          is_active?: boolean | null
          qr_code: string
          room_id?: number | null
          electronic_object?: string | null
          switch_is_active?: boolean | null
          switch_created_at?: string | null
        }
        Update: {
          allocated_at?: string | null
          allocated_to_customer_id?: number | null
          allocated_to_customer_name?: string | null
          created_at?: string | null
          device_code?: string
          device_icon?: string | null
          device_m2m_number?: string | null
          device_name?: string | null
          id?: number
          is_active?: boolean | null
          qr_code?: string
          room_id?: number | null
          electronic_object?: string | null
          switch_is_active?: boolean | null
          switch_created_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_devices_customer"
            columns: ["allocated_to_customer_id"]
            isOneToOne: false
            referencedRelation: "signup_users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "devices_room_id_fkey"
            columns: ["room_id"]
            isOneToOne: false
            referencedRelation: "rooms"
            referencedColumns: ["id"]
          },
        ]
      }
      device_shared_with: {
        Row: {
          id: number
          device_id: number
          shared_with_user_id: number
          shared_at: string
        }
        Insert: {
          id?: number
          device_id: number
          shared_with_user_id: number
          shared_at?: string
        }
        Update: {
          id?: number
          device_id?: number
          shared_with_user_id?: number
          shared_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "device_shared_with_device_id_fkey"
            columns: ["device_id"]
            isOneToOne: false
            referencedRelation: "devices"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "device_shared_with_shared_with_user_id_fkey"
            columns: ["shared_with_user_id"]
            isOneToOne: false
            referencedRelation: "signup_users"
            referencedColumns: ["id"]
          }
        ]
      }

      employee_data: {
        Row: {
          created_at: string
          email: string
          employee_id: string
          full_name: string
          id: number
          phone_number: string
          role: string
        }
        Insert: {
          created_at?: string
          email: string
          employee_id: string
          full_name: string
          id?: number
          phone_number: string
          role: string
        }
        Update: {
          created_at?: string
          email?: string
          employee_id?: string
          full_name?: string
          id?: number
          phone_number?: string
          role?: string
        }
        Relationships: []
      }
      employee_login_logs: {
        Row: {
          employee_id: string
          id: number
          login_time: string
        }
        Insert: {
          employee_id: string
          id?: number
          login_time: string
        }
        Update: {
          employee_id?: string
          id?: number
          login_time?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_employee_login_logs_employee_id"
            columns: ["employee_id"]
            isOneToOne: false
            referencedRelation: "employee_data"
            referencedColumns: ["employee_id"]
          }
        ]
      }
      login_users: {
        Row: {
          created_at: string | null
          email: string
          id: number
          password: string
        }
        Insert: {
          created_at?: string | null
          email: string
          id?: number
          password: string
        }
        Update: {
          created_at?: string | null
          email?: string
          id?: number
          password?: string
        }
        Relationships: []
      }
      otp_verifications: {
        Row: {
          created_at: string
          expires_at: string
          id: number
          is_verified: boolean
          otp: string
          phone_number: string
        }
        Insert: {
          created_at?: string
          expires_at?: string
          id?: number
          is_verified?: boolean
          otp: string
          phone_number: string
        }
        Update: {
          created_at?: string
          expires_at?: string
          id?: number
          is_verified?: boolean
          otp?: string
          phone_number?: string
        }
        Relationships: []
      }
      signup_users: {
        Row: {
          created_at: string | null
          email: string
          full_name: string
          id: number
          phone_number: string
          user_id: number
        }
        Insert: {
          created_at?: string | null
          email: string
          full_name: string
          id?: number
          phone_number: string
          user_id?: number
        }
        Update: {
          created_at?: string | null
          email?: string
          full_name?: string
          id?: number
          phone_number?: string
          user_id?: number
        }
        Relationships: []
      }
      super_admins: {
        Row: {
          created_at: string | null
          full_name: string
          id: number
          phone_number: string
        }
        Insert: {
          created_at?: string | null
          full_name: string
          id?: number
          phone_number: string
        }
        Update: {
          created_at?: string | null
          full_name?: string
          id?: number
          phone_number?: string
        }
        Relationships: []
      }
      houses: {
        Row: {
          id: number
          user_id: number
          house_name: string
          created_at: string | null
        }
        Insert: {
          id?: number
          user_id: number
          house_name: string
          created_at?: string | null
        }
        Update: {
          id?: number
          user_id?: number
          house_name?: string
          created_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "houses_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "signup_users"
            referencedColumns: ["id"]
          }
        ]
      }
      rooms: {
        Row: {
          id: number
          house_id: number
          room_type: string | null
          description: string | null
          created_at: string | null
        }
        Insert: {
          id?: number
          house_id: number
          room_type?: string | null
          description?: string | null
          created_at?: string | null
        }
        Update: {
          id?: number
          house_id?: number
          room_type?: string | null
          description?: string | null
          created_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "rooms_house_id_fkey"
            columns: ["house_id"]
            isOneToOne: false
            referencedRelation: "houses"
            referencedColumns: ["id"]
          }
        ]
      }

      switches: {
        Row: {
          id: number
          room_id: number
          electronic_object: string
          is_active: boolean | null
          created_at: string | null
        }
        Insert: {
          id?: number
          room_id: number
          electronic_object: string
          is_active?: boolean | null
          created_at?: string | null
        }
        Update: {
          id?: number
          room_id?: number
          electronic_object?: string
          is_active?: boolean | null
          created_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "switches_room_id_fkey"
            columns: ["room_id"]
            isOneToOne: false
            referencedRelation: "rooms"
            referencedColumns: ["id"]
          }
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

type DefaultSchema = Database[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
  | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
  | { schema: keyof Database },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof Database
  }
  ? keyof (Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
    Database[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
  : never = never,
> = DefaultSchemaTableNameOrOptions extends { schema: keyof Database }
  ? (Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
    Database[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
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
  | { schema: keyof Database },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof Database
  }
  ? keyof Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
  : never = never,
> = DefaultSchemaTableNameOrOptions extends { schema: keyof Database }
  ? Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
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
  | { schema: keyof Database },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof Database
  }
  ? keyof Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
  : never = never,
> = DefaultSchemaTableNameOrOptions extends { schema: keyof Database }
  ? Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
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
  | { schema: keyof Database },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof Database
  }
  ? keyof Database[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
  : never = never,
> = DefaultSchemaEnumNameOrOptions extends { schema: keyof Database }
  ? Database[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
  ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
  : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
  | keyof DefaultSchema["CompositeTypes"]
  | { schema: keyof Database },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof Database
  }
  ? keyof Database[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
  : never = never,
> = PublicCompositeTypeNameOrOptions extends { schema: keyof Database }
  ? Database[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
  ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
  : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const

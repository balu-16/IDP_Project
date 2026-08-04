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
      chats: {
        Row: {
          id: number
          user_id: number
          chat_name: string | null
          created_at: string
        }
        Insert: {
          id?: number
          user_id: number
          chat_name?: string | null
          created_at?: string
        }
        Update: {
          id?: number
          user_id?: number
          chat_name?: string | null
          created_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "chats_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "signup_users"
            referencedColumns: ["id"]
          },
        ]
      }
      chat_history: {
      Row: {
        id: number
        chat_id: number
        user_id: number
        input_data: string
        output_data: string
        created_at: string
        updated_at: string
        is_active: boolean
        title: string | null
      }
      Insert: {
        id?: number
        chat_id: number
        user_id: number
        input_data: string
        output_data: string
        created_at?: string
        updated_at?: string
        is_active?: boolean
        title?: string | null
      }
      Update: {
        id?: number
        chat_id?: number
        user_id?: number
        input_data?: string
        output_data?: string
        created_at?: string
        updated_at?: string
        is_active?: boolean
        title?: string | null
      }
      Relationships: [
        {
          foreignKeyName: "fk_chat"
          columns: ["chat_id"]
          isOneToOne: false
          referencedRelation: "chats"
          referencedColumns: ["id"]
        },
        {
          foreignKeyName: "chat_history_user_id_fkey"
          columns: ["user_id"]
          isOneToOne: false
          referencedRelation: "signup_users"
          referencedColumns: ["id"]
        },
      ]
    }
      signup_users: {
        Row: {
          id: number
          full_name: string
          email: string
          phone_number: string | null
          password: string
          created_at: string | null
        }
        Insert: {
          id?: number
          full_name: string
          email: string
          phone_number?: string | null
          password: string
          created_at?: string | null
        }
        Update: {
          id?: number
          full_name?: string
          email?: string
          phone_number?: string | null
          password?: string
          created_at?: string | null
        }
        Relationships: []
      }
      uploaded_files: {
        Row: {
          id: number
          chat_session_id: number
          file_name: string
          file_size: number
          file_type: string
          upload_timestamp: string
          user_id: number
        }
        Insert: {
          id?: number
          chat_session_id: number
          file_name: string
          file_size: number
          file_type: string
          upload_timestamp?: string
          user_id: number
        }
        Update: {
          id?: number
          chat_session_id?: number
          file_name?: string
          file_size?: number
          file_type?: string
          upload_timestamp?: string
          user_id?: number
        }
        Relationships: [
          {
            foreignKeyName: "uploaded_files_chat_session_id_fkey"
            columns: ["chat_session_id"]
            isOneToOne: false
            referencedRelation: "chats"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "uploaded_files_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "signup_users"
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
-- ============================================================
-- Fix Infinite Recursion in RLS
-- Resolves circular dependency between personas and persona_members policies
-- ============================================================

BEGIN;

-- 1. Create a helper function to check persona ownership bypassing RLS dependencies
CREATE OR REPLACE FUNCTION people.is_persona_owner(p_persona_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT EXISTS (
        SELECT 1 FROM people.personas 
        WHERE id = p_persona_id AND owner_user_id = auth.uid()
    );
$$;

-- 2. Drop the original recursive ALL policy on persona_members
DROP POLICY IF EXISTS "Owners manage members" ON people.persona_members;

-- 3. Replace with a non-recursive policy for managing members
CREATE POLICY "Owners manage members"
    ON people.persona_members FOR ALL
    USING (people.is_persona_owner(persona_id))
    WITH CHECK (people.is_persona_owner(persona_id));

COMMIT;

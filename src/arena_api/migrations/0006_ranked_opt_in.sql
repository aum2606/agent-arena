-- A fighter is spent by other players' ranked matches only if its owner says so (D-070); every fighter
-- that existed before starts out of the pool.
ALTER TABLE fighters ADD COLUMN ranked_opt_in boolean NOT NULL DEFAULT false;

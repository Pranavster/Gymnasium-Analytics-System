-- =========================
-- SCHEMA (optional if needed)
-- =========================
create schema if not exists gym_analytics;

-- DIMENSION TABLES
create table gym_analytics.members(
    member_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, full_name text, email text unique, phone varchar(12), date_of_birth date,
    join_date date default CURRENT_DATE, membership_tier text, is_active boolean default true,
    constraint membership_validity
        check (membership_tier in ('basic', 'standard', 'premium')),
    constraint phone_consistency
        check (phone ~ '^[0-9]{3}-[0-9]{3}-[0-9]{4}$')
);

create table gym_analytics.trainers(
    trainer_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, full_name text, email text unique, hire_date date, specialty text, hourly_rate numeric,
    constraint rate_check check (hourly_rate > 0)
);

create table gym_analytics.classes(
    class_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, class_name text, trainer_id int references gym_analytics.trainers(trainer_id), capacity int, duration_minutes int,
    class_type text,
    constraint capacity_check check (capacity between 1 and 100),
    constraint duration_check check (duration_minutes > 0),
    constraint class_type_check check (class_type in ('cardio', 'strength', 'flexibility', 'hiit'))
);
-- Schedules
create table gym_analytics.schedules(
    schedule_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, class_id int references gym_analytics.classes(class_id), trainer_id int references gym_analytics.trainers(trainer_id), 
	scheduled_at timestamptz, capacity int, status text default 'scheduled',
    constraint status_check check (status in ('scheduled', 'completed', 'cancelled'))
);
-- EVENT TABLES
create table gym_analytics.bookings(
    booking_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, member_id int references gym_analytics.members(member_id),
    schedule_id int references gym_analytics.schedules(schedule_id), booked_at timestamptz default now()
);


create table gym_analytics.attendance(
    member_id int references gym_analytics.members(member_id), schedule_id int references gym_analytics.schedules(schedule_id),
    check_in_time timestamptz, attendance_status text, primary key (member_id, schedule_id)
);

create table gym_analytics.cancellations(
    booking_id int references gym_analytics.bookings(booking_id), cancelled_at timestamptz, cancellation_type text,
    constraint cancellation_type_check check (cancellation_type in ('early', 'late', 'system'))
);

create table gym_analytics.trainer_sessions(
    session_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, trainer_id int references gym_analytics.trainers(trainer_id), member_id int references gym_analytics.members(member_id), 
	session_date date, duration_minutes int, rate_charged numeric(5,2),
    constraint duration_check check (duration_minutes > 0),
    constraint rate_charged_check check (rate_charged > 0)
);

-- SCHEDULE TABLE


create table gym_analytics.payments(
    payment_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, member_id int references gym_analytics.members(member_id), amount numeric, payment_date timestamptz default now(), 
	payment_type text, notes text,
    constraint payment_type_check check (payment_type in ('membership', 'personal_training', 'drop_in')),
    constraint amount_check check (amount > 0)
);

do $$
declare
	r record;
begin
	for r in (select tablename from pg_tables where schemaname = 'gym_analytics') loop
		execute 'drop table if exists gym_analytics.' || quote_ident(r.tablename) || ' cascade';
	end loop;
end $$;



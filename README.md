pfsmorigo scripts
=================


pomodoro
--------

Commands available: `start`, `stop`, `shortbreak`, `longbreak`, `set` and `reset`.

Without parameters it will show the current state of pomodoro, e.g.:

    $ pomodoro
    T 02:05:49 (7)

First part is the letter representing the state. It could be started (S), stopped (T), short break (B) or long break (L).

Second part is the time releated to the last state change. It will be a countdown for the started and breaks states and a countup for the stopped state.

The last part is a counter for the number of completed pomodoros.

### Important notes

 * After the started state finishs it will automatically change to a break state;
 * The break state could be short or long depending on the counter total;


### Example of usage

    $ pomodoro start
    S 00:25:00 (7)
    $ pomodoro
    S 00:24:53 (7)

 

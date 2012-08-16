class FSMError(Exception):
    def __init__(self, msg):
        #Exception.__init__(self, value)
        self.msg = msg
    def __str__(self):
        return self.msg

class TransitionError(FSMError):
    def __init__(self, msg=""):
        FSMError.__init__(self, msg)

class StateMachine:
    def __init__(self):
        self.states = {}
        self.state = None

    def add(self, state, input, newstate, action=None):
        try:
            self.states[state][input] = (newstate, action)
        except KeyError:
            self.states[state] = {}
            self.states[state][input] = (newstate, action)

    def execute(self, input, args):
        if self.state not in self.states:
            raise FSMError("invalid state: %s" % self.state)
        state = self.states[self.state]
        if input in state:
            newstate, action = state[input]
            if action is not None:
                action(self.state, input, args)
            self.state = newstate
        else:
            if None in state:
                newstate, action = state[None]
                if action is not None:
                    action(self.state, input, args)
                self.state = newstate
            else:
                raise TransitionError, 'input not recognized: %s:%s',\
                    (self.inp, self.curr)

    def start(self, state):
        self.state = state

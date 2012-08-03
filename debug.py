## {{{ http://code.activestate.com/recipes/52215/ (r1)
import sys
import traceback
def backtrace(debug_locals=True):
    tb = sys.exc_info()[2]
    while 1:
        if not tb.tb_next:
            break
        tb = tb.tb_next
    stack = []
    f = tb.tb_frame
    while f:
        stack.append(f)
        f = f.f_back
    stack.reverse()
    print "Locals by frame, innermost last"
    for frame in stack:
        print
        print "Frame %s in %s at line %s" % (frame.f_code.co_name,
                                             frame.f_code.co_filename,
                                             frame.f_lineno)
        if debug_locals:
            for key, value in frame.f_locals.items():
                print "\t%20s = " % key,
                try:
                    print value
                except:
                    print "<ERROR WHILE PRINTING VALUE>"
    print
    traceback.print_exc()
## end of http://code.activestate.com/recipes/52215/ }}}

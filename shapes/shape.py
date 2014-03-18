import config as cfg
import numpy as np

class Shape(object):
    """Base class for different shape objects, e.g. sigmoid.    
       Derived classes should implement:
           n = n_params()
           str = cache_name()
           str = format_params(theta, latex=False)
           y = f(theta,x)           
           d_theta = f_grad(theta,x)
           theta0 = get_theta_guess(x,y)
    """
    def __init__(self, priors):
        """Prior function for each parameter should be passed by the derived class.
           NOTE: We are modeling distributions as independent, which may not be good enough later on.
                 If this assumption changes, some code will need to move around.
        """
        self.priors = priors

    def __str__(self):
        return self.cache_name()

    def bounds(self):
        return [pr.bounds() for pr in self.priors]

    def log_prob_theta(self, theta):
        # NOTE: This assumes the priors for different parameters are independent
        return sum(pr.log_prob(t) for pr,t in zip(self.priors,theta))
        
    def d_log_prob_theta(self, theta):
        # NOTE: This assumes the priors for different parameters are independent
        return np.array([pr.d_log_prob(t) for pr,t in zip(self.priors,theta)])

    def high_res_preds(self, theta, x):
        x_smooth = np.linspace(x.min(),x.max(),cfg.n_curve_points_to_plot)
        y_smooth = self.f(theta, x_smooth)
        return x_smooth,y_smooth

    def TEST_check_grad(self, n=100, threshold=1E-7):
        import scipy.optimize
        rng = np.random.RandomState(0)
        def check_one():
            x = rng.uniform(-10,10)
            theta = rng.uniform(size=self.n_params())
            diff = scipy.optimize.check_grad(self.f, self.f_grad, theta, x)
            return diff
        max_diff = max([check_one() for _ in xrange(n)])
        print 'Max difference over {} iterations: {}'.format(n,max_diff)
        if max_diff < threshold:
            print 'Gradient is OK'
        else:
            print 'Difference is too big. Gradient is NOT OK!'

#####################################################
# Building shape from command line input
#####################################################
def allowed_shape_names():
    return ['sigmoid', 'poly0', 'poly1', 'poly2', 'poly3']

def get_shape_by_name(shape_name):
    import re
    if shape_name == 'sigmoid':
        from sigmoid import Sigmoid
        return Sigmoid()
    elif shape_name.startswith('poly'):
        m = re.match('poly(\d)',shape_name)
        assert m, 'Illegal polynomial shape name'
        degree = int(m.group(1))
        from poly import Poly
        return Poly(degree)
    else:
        raise Exception('Unknown shape: {}'.format(shape_name))
